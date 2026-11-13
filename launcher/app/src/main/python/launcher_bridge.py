"""Android host for the existing backend, with private, hash-checked files."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import threading
import zipfile

_ROOT = None
_PRIVATE = None
_THREAD = None
_STOP = threading.Event()
_STATUS = {'phase': 'stopped', 'detail': 'Stopped'}
_LOCK = threading.RLock()
_OPERATIONS = threading.RLock()


def _status(phase, detail, *, playable=False):
    global _STATUS
    with _LOCK:
        _STATUS = {'phase': phase, 'detail': detail, 'playable': playable}
        return json.dumps(_STATUS)


def status():
    with _LOCK:
        return json.dumps(_STATUS)


def unpack_verified(archive_path, manifest, destination):
    """Exact file set and hashes; reject aliases, traversal and oversized data."""
    expected = manifest['files']
    if len(expected) > 5000:
        raise ValueError('Too many runtime files')
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError('Runtime file set differs')
        total = 0
        for info in archive.infolist():
            name = PurePosixPath(info.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in info.filename:
                raise ValueError('Unsafe runtime path')
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Runtime aliases refused')
            total += info.file_size
            if total > 128 * 1024 * 1024:
                raise ValueError('Runtime data exceeds limit')
            raw = archive.read(info)
            if hashlib.sha256(raw).hexdigest() != expected[info.filename]:
                raise ValueError('Runtime hash differs: ' + info.filename)
            path = destination.joinpath(*name.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)


def install(files_dir, *, refresh_content=False):
    with _OPERATIONS:
        return _install(files_dir, refresh_content=refresh_content)


def _install(files_dir, *, refresh_content=False):
    global _ROOT, _PRIVATE
    private = Path(files_dir)
    if _ROOT is not None and _PRIVATE == private and not refresh_content:
        return str(_ROOT)
    bundle = private / 'runtime.zip'
    manifest = json.loads((private / 'runtime-manifest.json').read_bytes())
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    if digest != manifest['archive_sha256']:
        raise ValueError('Runtime archive hash differs')
    root = private / 'runtime' / digest
    if not root.exists():
        root.parent.mkdir(parents=True, exist_ok=True)
        temporary = root.with_name(digest + '.installing')
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir()
        try:
            unpack_verified(bundle, manifest, temporary)
            os.replace(temporary, root)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    content_manifest = private / 'content-manifest.json'
    content = json.loads(content_manifest.read_bytes()) if content_manifest.is_file() else None
    if content and content.get('version') == 2:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from server import mobile_content, mobile_special_catalog
        raw = content_manifest.read_bytes()
        mobile_content.manifest(raw)
        shared = mobile_content.destination(private, raw)
        for name in content['files']:
            target = root / name
            if not target.exists() and not target.is_symlink():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(shared / name)
        catalog = (root / 'server/data/android-special-catalog.json').read_bytes()
        if hashlib.sha256(catalog).hexdigest() != content['special_catalog_sha256']:
            raise ValueError('Bundled reconstruction catalog differs')
        mobile_special_catalog.configure(root, catalog)
    elif content:
        # Read-only compatibility with already installed prototype resources.
        expected = json.loads(content_manifest.read_bytes())['files']
        shared = private / 'content'
        for name, digest in expected.items():
            stored = shared / name
            target = root / name
            if not stored.exists():
                # Upgrade the already imported prototype without duplicating
                # game data for every backend code version.
                for old in sorted(root.parent.iterdir()):
                    candidate = old / name
                    if old != root and candidate.is_file() and not candidate.is_symlink():
                        if hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
                            continue
                        stored.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(candidate, stored)
                        break
            if stored.is_file() and not target.exists() and not target.is_symlink():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(stored)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    _ROOT = root
    _PRIVATE = private
    return str(root)


def self_test(files_dir):
    root = install(files_dir)
    from server.account_progression import level_state
    from server.welcome_gift import policy
    progression = level_state(700)
    return json.dumps({
        'python': sys.version.split()[0],
        'runtime_root': root,
        'progression': progression,
        'welcome_heading': policy()['popup']['heading'][1],
        'backend_code': 'existing server modules',
        'gameplay_certified': False,
    })


def game_versions(files_dir):
    install(files_dir)
    from server.game_versions import policy
    return json.dumps(policy())


def _dex_recipe(original, plan, shim, holders):
    """Run the launcher's DexRecipe (dexlib2) on the user's own classes.dex."""
    from java import jclass
    recipe = jclass('org.ignition.recipe.DexRecipe')
    return bytes(recipe.apply(original, plan, shim, holders))


def prepare_game(files_dir, original_path, version_code):
    with _OPERATIONS:
        install(files_dir)
        from server.mobile_game_recipe import prepare
        private = Path(files_dir)
        return json.dumps(prepare(original_path, private / 'game-recipe.zip',
                                  private / 'game-install/unsigned.apk', int(version_code),
                                  _dex_recipe))


def game_recipe_accepts(files_dir, record_json):
    install(files_dir)
    from server.mobile_game_recipe import accepts
    return accepts(Path(files_dir) / 'game-recipe.zip', json.loads(record_json))


def content_ready(files_dir):
    install(files_dir)
    from server.mobile_content import ready
    return ready(files_dir, (Path(files_dir) / 'content-manifest.json').read_bytes())


def prepare_expansions(files_dir, sources_json):
    with _OPERATIONS:
        install(files_dir)
        from server.mobile_content import prepare
        previous = status()
        _status('preparing', 'Preparing game data…')
        try:
            prepare(files_dir, (Path(files_dir) / 'content-manifest.json').read_bytes(),
                    json.loads(sources_json))
            from server.local_content_source import cards
            from server.reconstructed_specials import versions
            result = {'base_cards': len(cards()), 'specials': len(versions())}
        except Exception as error:
            _status('error', str(error))
            raise
        prior = json.loads(previous)
        if prior['phase'] == 'running':
            _status('running', prior['detail'], playable=prior.get('playable', False))
        else:
            _status('stopped', 'Game data ready')
        return json.dumps(result)


def clubs(files_dir):
    install(files_dir)
    from server.mobile_clubs import ClubFiles
    return ClubFiles(files_dir)


def _adopt_prototype(files_dir, state):
    if state.current() is not None or state.available():
        return
    old = Path(files_dir) / 'backend-argv.json'
    if not old.exists():
        return
    argv = json.loads(old.read_bytes())
    if '--profile-state' not in argv:
        raise ValueError('Unknown previous club configuration')
    source = Path(argv[argv.index('--profile-state') + 1]).resolve().parent
    if Path(files_dir).resolve() not in source.parents:
        raise ValueError('Previous club is outside Ignition storage')
    from server import account_backup
    staging = _ROOT / 'reports/ignition-prototype/isolated-account'
    staging.parent.mkdir(parents=True, exist_ok=True)
    if not staging.exists():
        account_backup.create_backup(source, staging, quiescent=True)
    import tarfile
    archive = Path(files_dir) / 'prototype-club.tar.gz'
    with tarfile.open(archive, 'w:gz') as packed:
        for path in sorted(staging.iterdir()):
            packed.add(path, arcname='fifa16-account/' + path.name, recursive=False)
    state.import_backup(archive)
    archive.unlink()
    old.rename(old.with_name('prototype-backend-argv.json'))


def import_club(files_dir, archive_path):
    with _OPERATIONS:
        check_idle(files_dir, leaving=True)
        stop()
        state = clubs(files_dir)
        result = state.import_backup(archive_path)
        return json.dumps(result)


def export_club(files_dir):
    with _OPERATIONS:
        state = clubs(files_dir)
        selected = state.current()
        if selected is None or selected['pending']:
            raise ValueError('Complete club setup before exporting')
        # Refuse before stopping a running match; backup validates again after
        # the listener has drained. Never abort play just to make an export.
        from server.account_transaction import ACCOUNT_LOCK
        from server.account_backup import validate_account
        with ACCOUNT_LOCK:
            validate_account(Path(selected['account']))
        was_running = _THREAD is not None and _THREAD.is_alive()
        stop()
        try:
            return state.export_backup()
        finally:
            if was_running:
                start(files_dir)


def list_clubs(files_dir):
    with _OPERATIONS:
        state = clubs(files_dir)
        _adopt_prototype(files_dir, state)
        return json.dumps(state.available())


def selected_club(files_dir):
    with _OPERATIONS:
        install(files_dir)
        content = Path(files_dir) / 'content-manifest.json'
        if content.is_file() and json.loads(content.read_bytes()).get('version') == 2:
            if not content_ready(files_dir):
                return json.dumps({'name': 'Import expansions in Setup', 'pending': True})
        state = clubs(files_dir)
        _adopt_prototype(files_dir, state)
        return json.dumps(state.current() or {'name': 'New club'})


def check_idle(files_dir, *, leaving=False):
    """Refuse while the selected club may be mid-session.

    leaving=True (new/select/import: the selected club is only switched away
    from) tolerates a club whose recorded Store policy is stale: it cannot
    start, so it cannot be mid-session. Its account validation needs a valid
    runtime selection, so it is skipped; the club's files (including any
    recovery journal) are never read for repair or changed. Operations on the
    club itself stay strict.
    """
    state = clubs(files_dir)
    selected = state.current()
    if selected is not None and not selected['pending']:
        from server.account_transaction import ACCOUNT_LOCK
        from server.account_backup import validate_account
        from server import fresh_account_runtime
        with ACCOUNT_LOCK:
            account = Path(selected['account'])
            # A cold launcher has not started the listener's profile selection.
            # Select only the already validated current save, without preparing,
            # repairing or reseeding it. Keep an active selector's hash guard.
            try:
                if not fresh_account_runtime.selected(account):
                    fresh_account_runtime.configure(account)
            except fresh_account_runtime.StaleRuntimePolicy:
                if not leaving:
                    raise
                return True
            validate_account(account)
    return True


def club_needs_update(files_dir):
    """True when the selected club only needs its Store policy brought current."""
    state = clubs(files_dir)
    selected = state.current()
    if selected is None or selected['pending']:
        return False
    from server import fresh_account_runtime
    try:
        return fresh_account_runtime.stale(Path(selected['account']))
    except ValueError:
        return False  # any other problem is reported by start() as before


def update_club(files_dir):
    """Explicit, user-confirmed update of a stale club (snapshot + rollback)."""
    with _OPERATIONS:
        stop()
        state = clubs(files_dir)
        selected = state.current()
        if selected is None or selected['pending']:
            raise ValueError('No saved club is selected')
        from server import fresh_account_runtime
        from server.account_transaction import ACCOUNT_LOCK
        with ACCOUNT_LOCK:
            result = fresh_account_runtime.readmit(
                Path(selected['account']), Path(files_dir) / 'exports')
        return json.dumps(result)


def new_club(files_dir):
    with _OPERATIONS:
        check_idle(files_dir, leaving=True)
        stop()
        return json.dumps(clubs(files_dir).create_new())


def godmode(files_dir):
    with _OPERATIONS:
        check_idle(files_dir)
        state = clubs(files_dir)
        selected = state.current()
        if selected is None or selected['pending']:
            raise ValueError('Complete club setup before using GODMODE')
        was_running = _THREAD is not None and _THREAD.is_alive()
        stop()
        try:
            return json.dumps(state.godmode())
        finally:
            if was_running:
                start(files_dir)


def select_club(files_dir, identifier):
    with _OPERATIONS:
        check_idle(files_dir, leaving=True)
        stop()
        state = clubs(files_dir)
        state.select(identifier)
        return json.dumps(state.current())


def start(files_dir):
    global _THREAD
    with _OPERATIONS:
        if _THREAD is not None and _THREAD.is_alive():
            return status()
        install(files_dir)
        from server import client_build
        client_build.configure(Path(files_dir) / 'game-install/prepared.json')
        # Data validation precedes allocating a new save or setup identity.
        from server.local_content_source import cards
        cards()
        state = clubs(files_dir)
        _adopt_prototype(files_dir, state)
        selected = state.ensure()
        account = Path(selected['account'])
        from server import fresh_account_runtime, mobile_setup_session
        mobile_setup_session.configure(account if selected['pending'] or
            mobile_setup_session.path_for(account).exists() else None)
        from server.welcome_gift import recover_readiness
        recover_readiness(account, Path(files_dir) / 'http.jsonl')
        runtime_update = None
        if selected['pending']:
            from server.mobile_clubs import setup_arguments
            control = state.setup_control()
            argv = setup_arguments(account, control, Path(files_dir) / 'http.jsonl')

            def runtime_update():
                if not account.exists():
                    return None
                # Publication of the original CreateUser result is the grant
                # boundary. Its complete stores are admitted, never reseeded.
                fresh_account_runtime.prepare(account)
                return fresh_account_runtime.argv(account, output=Path(files_dir) / 'http.jsonl')[2:]
        else:
            fresh_account_runtime.prepare(account)
            argv = fresh_account_runtime.argv(account, output=Path(files_dir) / 'http.jsonl')[2:]
        _STOP.clear()
        _status('starting', 'Starting…')

        def run():
            try:
                from server.reachability import main
                main(argv, stop_event=_STOP, local_transport=True,
                     runtime_update=runtime_update, on_ready=lambda port: _status(
                         'running', 'Ready', playable=True,
                     ))
                _status('stopped', 'Stopped')
            except BaseException as error:
                import traceback
                (Path(files_dir) / 'backend-error.txt').write_text(traceback.format_exc())
                _status('error', type(error).__name__ + ': ' + str(error))

        _THREAD = threading.Thread(target=run, name='ignition-backend', daemon=True)
        _THREAD.start()
        return status()


def stop():
    _STOP.set()
    thread = _THREAD
    if thread is not None and thread.is_alive():
        _status('stopping', 'Finishing requests…')
        thread.join()
    return status()
