"""Ignition save selection over the existing authoritative account stores.

The only new durable state is the last-loaded save ID. Wallets, inventory,
fixtures and rewards keep using their existing journals and recovery rules.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import uuid

from .account_transaction import atomic

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'fifa16-account/'
_VALID_SETUP_CONTROLS = set()


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def save_id(value):
    if type(value) is not str or str(uuid.UUID(value)) != value:
        raise ValueError('Invalid save ID')
    return value


def validate_setup_control(raw):
    digest = hashlib.sha256(raw).digest()
    if digest in _VALID_SETUP_CONTROLS:
        return
    value = json.loads(raw)
    if (type(value) is not dict or type(value.get('requests')) is not dict
            or any(type(key) is not str or mode not in ('pass', 'hold', 'close')
                   for key, mode in value['requests'].items())):
        raise ValueError('Invalid saved setup transport; files preserved')
    if len(_VALID_SETUP_CONTROLS) >= 64:
        _VALID_SETUP_CONTROLS.clear()
    _VALID_SETUP_CONTROLS.add(digest)


def extract_backup(archive_path, destination):
    destination.mkdir(parents=True)
    names = set()
    total = 0
    with tarfile.open(archive_path, 'r:gz') as archive:
        for member in archive:
            name = member.name[len(PREFIX):] if member.name.startswith(PREFIX) else ''
            if (not member.isfile() or not name or '/' in name or '\\' in name
                    or name in ('.', '..') or name in names):
                raise ValueError('Unsupported club backup entry')
            names.add(name)
            total += member.size
            if len(names) > 500 or total > 128 * 1024 * 1024:
                raise ValueError('Club backup exceeds the import limit')
            with archive.extractfile(member) as source:
                (destination / name).write_bytes(source.read())


class ClubFiles:
    def __init__(self, private):
        self.private = Path(private).resolve()
        self.folder = self.private / 'saves'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.selection = self.private / 'last-club.json'

    def account(self, identifier):
        path = self.folder / save_id(identifier) / 'isolated-account'
        if path.is_symlink() or path.resolve() != path:
            raise ValueError('Save alias refused')
        return path

    def select(self, identifier):
        self.describe(identifier)
        atomic(self.selection, encode({'version': 1, 'last_club': identifier}))

    def describe(self, identifier):
        from .first_run_account import inspect, pending_session
        account = self.account(identifier)
        if account.exists():
            inspect(account)
            from .local_profile import load_profile
            profile = load_profile(account / 'profile.json')
            return {'id': identifier, 'account': str(account), 'pending': False,
                    'name': profile.club_name, 'coins': profile.credits}
        if pending_session(account) is not None:
            return {'id': identifier, 'account': str(account), 'pending': True,
                    'name': 'New club', 'coins': 0}
        raise ValueError('Selected club is missing; existing saves were preserved')

    def current(self):
        if not self.selection.exists():
            return None
        if self.selection.is_symlink():
            raise ValueError('Save selection alias refused')
        value = json.loads(self.selection.read_bytes())
        if set(value) != {'version', 'last_club'} or value['version'] != 1:
            raise ValueError('Invalid last-loaded club record')
        return self.describe(save_id(value['last_club']))

    def available(self):
        result = []
        for path in sorted(self.folder.iterdir()):
            if path.is_dir():
                result.append(self.describe(save_id(path.name)))
        return result

    def ensure(self):
        selected = self.current()
        if selected is not None:
            return selected
        # Recover a single orphan from interruption before pointer publication.
        existing = self.available()
        if existing:
            if len(existing) != 1:
                raise ValueError('Select a club; multiple saves are present')
            self.select(existing[0]['id'])
            return existing[0]
        return self.create_new()

    def create_new(self):
        from .first_run_account import begin_setup
        identifier = str(uuid.uuid4())
        account = self.account(identifier)
        account.parent.mkdir()
        begin_setup(account, creation_id=identifier)
        self.select(identifier)
        return self.describe(identifier)

    def import_backup(self, archive_path):
        from . import account_backup, fresh_account_runtime
        identifier = str(uuid.uuid4())
        work = ROOT / 'reports/ignition-transfers' / identifier
        source = work / 'source/isolated-account'
        restored = work / 'restored/isolated-account'
        extract_backup(archive_path, source)
        restored.parent.mkdir(parents=True)
        account_backup.import_account(source, restored)
        if not (restored / 'first-run-completion.json').is_file():
            raise ValueError('This backup needs legacy profile migration; import preserved')
        fresh_account_runtime.validate(restored)
        destination = self.account(identifier)
        destination.parent.mkdir()
        for name in account_backup.SELECTORS:
            path = restored / name
            if path.exists():
                path.write_bytes(account_backup.rebound(
                    path.read_bytes(), str(restored), str(destination),
                ))
        os.rename(restored, destination)
        try:
            fresh_account_runtime.validate(destination)
        except Exception:
            # Refuse a conflicting import without exposing an invalid save in
            # the picker. Retain its staging evidence and the previous selection.
            os.rename(destination, restored)
            destination.parent.rmdir()
            raise
        self.select(identifier)
        shutil.rmtree(work)
        return self.describe(identifier)

    def setup_control(self):
        """Keep a pending club's transport configuration across process death."""
        from .first_run_catalog import initial_control
        from .mobile_setup_session import path_for
        selected = self.current()
        if selected is None or not selected['pending']:
            raise ValueError('Pending club required for setup transport')
        account = Path(selected['account'])
        destination = account.parent / 'setup-control.json'
        if destination.exists():
            raw = destination.read_bytes()
        else:
            legacy = self.private / 'setup-control.json'
            if legacy.exists() and path_for(account).exists():
                pending = [row for row in self.available() if row['pending']]
                if len(pending) != 1:
                    raise ValueError('Legacy setup transport owner is ambiguous; files preserved')
                raw = legacy.read_bytes()
            else:
                raw = encode(initial_control())
        validate_setup_control(raw)
        if not destination.exists():
            atomic(destination, raw)
        return destination

    def export_backup(self):
        from . import account_backup
        selected = self.current()
        if selected is None or selected['pending']:
            raise ValueError('Complete club setup before exporting')
        identifier = str(uuid.uuid4())
        work = ROOT / 'reports/ignition-transfers' / identifier
        staging = work / 'isolated-account'
        work.mkdir(parents=True)
        account_backup.create_backup(Path(selected['account']), staging, quiescent=True)
        exports = self.private / 'exports'
        exports.mkdir(exist_ok=True)
        destination = exports / ('ignition-' + identifier + '.tar.gz')
        temporary = destination.with_suffix('.new')
        with tarfile.open(temporary, 'w:gz') as archive:
            for path in sorted(staging.iterdir()):
                archive.add(path, arcname=PREFIX + path.name, recursive=False)
        os.replace(temporary, destination)
        shutil.rmtree(work)
        return str(destination)

    def godmode(self):
        """Refill the selected club's FP after the caller drains its backend.

        This is an explicit launcher action, not an earned reward or payment.
        A single atomic profile replacement is retry-stable without a new journal.
        """
        from dataclasses import replace
        from .account_backup import validate_account
        from .account_transaction import ACCOUNT_LOCK
        from .local_profile import ProfileStore

        selected = self.current()
        if selected is None or selected['pending']:
            raise ValueError('Complete club setup before using GODMODE')
        account = Path(selected['account'])
        profile = ProfileStore(account / 'profile.json')
        with ACCOUNT_LOCK:
            validate_account(account)
            before = profile.load()
            backup = None
            if before.fifa_points != 999999:
                backup = self.export_backup()
                with profile.transaction():
                    if profile.load() != before:
                        raise ValueError('Club changed during backup; FP left unchanged')
                    profile.save(replace(before, fifa_points=999999))
            return {
                'id': selected['id'], 'club': selected['name'],
                'fifa_points': 999999, 'changed': before.fifa_points != 999999,
                'backup': backup,
            }


def setup_arguments(account, control, output, port=18081):
    """Previously certified startup/FTF routes; no match rewards before creation."""
    account = Path(account)
    flags = (
        '--persona-id', '1', '--fut-auth-code', '--victory-auth-code',
        '--victory-session', '--game-session', '--settings', '--match-reset',
        '--user-info', '--purchased-items', '--finalize-authentication',
        '--finalize-queue-prerequisites', '--persona-accomplishments',
        '--user-credits', '--cycle-session', '--goal-event', '--save-squad',
    )
    result = ['--output', str(output), '--port', str(port), *flags,
              '--startup-control', str(control)]
    for flag, name in (
        ('--profile-state', 'profile.json'), ('--football-state', 'football.json'),
        ('--football-catalog', 'content.json'), ('--revival-pack-state', 'packs.json'),
    ):
        result.extend((flag, str(account / name)))
    return result
