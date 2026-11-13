"""Validated quiescent account backups and restoration (FIRST-003).

Every account file is classified (state journal, static configuration or
release selector); unknown files are refused so new stores cannot be silently
left out. Backups copy all account JSON bytes and validate each state journal
read-only. Pending/interrupted transactions are refused, never repaired here.

Release selectors embed the absolute account path they were admitted for, so a
backup restores two ways:

- into a NEW reports/.../isolated-account (inspection copy; selectors bound to
  the original path stay inactive there), or
- back to its ORIGINAL path after the damaged account was set aside (the
  returning-player case), or
- into another account path (import), rebinding the selectors that named the
  source. The user pre-authorized local export/import of the normal account
  (5 November 2026); scripts/account_transfer.py wraps that workflow.

Nothing is ever deleted: set_aside renames an account to a dated sibling.
This helper does not start services, change routing or recover source stores.
"""
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path

from scripts.lab_evidence import SNAPSHOT_MANIFEST, file_digest, json_files, new_json, now, snapshot
from .local_content import ContentCatalog
from .local_football import FootballStore
from .local_packs import PackStore
from .local_profile import ProfileStore
from .local_purchase import PurchaseStore
from .local_seasons import SeasonStore, load_definition
from .local_store import products

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / 'server/data/development/fm16in2026'
MANIFEST = '.fifa-backup-manifest'
LAB_MANIFEST_COPY = '.fifa-backup-lab-snapshot'
SCHEMA = 3
EXCHANGE_POLICY = ROOT / 'server/policy/player-exchange-revival-v2.json'

REQUIRED = {
    'profile.json', 'football.json', 'content.json', 'packs.json', 'purchases.json',
    'products.json', 'definition.json', 'definition-response.json',
    'no-current-response.json', 'seasons.json', 'control.json', 'manifest.json',
}
STATE = {
    'first-run-completion.json',
    'profile.json', 'football.json', 'packs.json', 'purchases.json', 'seasons.json',
    'native-seasons.json', 'free-coins.json', 'free-packs.json', 'quick-sells.json',
    'market.json', 'pack-sessions.json', 'player-exchanges.json',
    'item-history.json',
    'accomplishments.json',
    # 1577 same-session lineups replaced by squad saves (stale Sim PlaySim).
    'squad-lineup-history.json',
    # FIRST-002 starter club receipt (seed and granted references).
    'first-run-grant.json',
    # Tournament ledgers appear once a cup is played (one file per cup).
    'native-tournament-sim.json', 'native-tournaments.json', 'native-tournaments-202.json',
    'native-tournaments-203.json', 'native-tournaments-204.json', 'native-tournaments-205.json',
}
STATIC = {
    'content.json', 'products.json', 'definition.json', 'definition-response.json',
    'no-current-response.json', 'control.json', 'manifest.json',
}
SELECTORS = {
    'account-runtime.json',
    # Append-only record of explicit club updates (fresh_account_runtime.readmit).
    'account-runtime-history.json',
    'welcome-gift.json',
    'atomic-match-release.json', 'club-item-actions-release.json',
    'consumable-effects-release.json', 'division-season-identity-release.json',
    'gameplay-release.json', 'market-release.json', 'market-release-v2.json',
    'market-release-v3.json', 'match-forfeit-release.json',
    'native-paid-pack-presentation.json', 'native-source-pack-presentation.json',
    'pack-session-release.json', 'played-identity-release.json',
    'played-match-release.json', 'player-exchange-release.json', 'reward-release.json',
    'season-choice-release.json', 'season-forfeit-release.json',
    'sim-completion-release.json', 'squad-management-release.json',
    'squad-slot-authority.json', 'store-direct-delivery.json', 'store-release.json',
    'store-single-candidate.json', 'tournament-release.json', 'tournament-release-v2.json',
    'level-rewards.json',
    'draw-history-seal.json',
    'accomplishments-select.json',
    'store-demo-offers.json',
    'market-supply-big5.json',
    'market-supply-scale.json',
    'first-run.json',
    # Isolated-lab candidates/probes (never present on the normal account).
    'pack-session-candidate.json', 'tournament-presentation-probe.json',
}
# Transient intent files exist only while a commit is interrupted.
TRANSIENT = {'market-intent.json': 'Recover pending Market settlement before backup'}
KNOWN = STATE | STATIC | SELECTORS
LOCK_ORDER = (
    'player-exchanges', 'quick-sells', 'free-packs', 'free-coins', 'native-seasons',
    'purchases.json', 'packs.json', 'profile.json', 'football.json', 'seasons.json',
)
MANIFEST_KEYS = {
    1: {'schema', 'kind', 'utc', 'account', 'files', 'coherence', 'resources'},
    2: {'schema', 'kind', 'utc', 'account', 'domains', 'source', 'selector_accounts',
        'lab_snapshot', 'files', 'coherence', 'resources'},
    # 3 records the project folder so imports survive a moved/installed project.
    3: {'schema', 'kind', 'utc', 'account', 'domains', 'source', 'root', 'selector_accounts',
        'lab_snapshot', 'files', 'coherence', 'resources'},
}


def safe_destination(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Account destination alias refused')
    result = path.resolve()
    if ROOT / 'reports' not in result.parents or result.name != 'isolated-account':
        raise ValueError('New reports/.../isolated-account destination required')
    if result.exists():
        raise FileExistsError('Existing account will never be replaced')
    return result


def account_files(path):
    path = Path(path)
    for file in path.glob('*.json'):
        if file.is_symlink():
            raise ValueError('Account file alias refused')
    files = json_files(path)
    for name, message in TRANSIENT.items():
        if name in files:
            raise ValueError(message)
    if not REQUIRED <= set(files):
        raise ValueError('Incomplete account bundle')
    unknown = sorted(set(files) - KNOWN)
    if unknown:
        raise ValueError('Unsupported account files: ' + ', '.join(unknown))
    return files


def running_backends(account):
    """PIDs of local backends whose argv names a file in this account."""
    account = Path(account).resolve()
    found = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = [a.decode(errors='replace') for a in (entry / 'cmdline').read_bytes().split(b'\0') if a]
        except OSError:
            continue
        if not any(a.endswith('reachability.py') for a in argv):
            continue
        if any(Path(a).parent == account for a in argv if a.startswith('/')):
            found.append(int(entry.name))
    return found


def require_stopped(account):
    pids = running_backends(account)
    if pids:
        raise ValueError(f'Stop the backend serving this account first (PIDs {pids})')


def validate_account(path):
    path = Path(path)
    account_files(path)
    profile = ProfileStore(path / 'profile.json')
    p = profile.load()
    content = ContentCatalog(path / 'content.json')
    FootballStore(path / 'football.json', content).load(p.persona_id)
    definition = load_definition(path / 'definition.json')
    season = SeasonStore(path / 'seasons.json', definition).load()
    packs = PackStore(path / 'packs.json')
    inventory = packs.load(p.persona_id)
    purchases = PurchaseStore(path / 'purchases.json', profile, packs, path / 'products.json')
    wallet = purchases.load()
    products(path / 'products.json')
    if 'prepared' in inventory or 'prepared' in wallet:
        raise ValueError('Recover pending opening/purchase before backup')
    if (path / 'free-coins.json').exists():
        from .native_free_coins import FreeCoinsCoordinator
        # Validate receipt ownership/retirement without activating an adapter,
        # repairing an intent or writing to this archived account.
        FreeCoinsCoordinator(path, enabled=True).inspect()
    if (path / 'free-packs.json').exists():
        from .native_free_packs import FreePacksCoordinator
        FreePacksCoordinator(path, enabled=True).inspect()
    elif inventory.get('voucher_grants'):
        raise ValueError('Voucher ownership lacks source journal')
    if (path / 'quick-sells.json').exists():
        from .native_quick_sell import QuickSellCoordinator
        QuickSellCoordinator(path, enabled=True).inspect()
    if p.division_offline != definition.division_index:
        raise ValueError('Profile/definition division conflict')
    if (path / 'native-seasons.json').exists():
        validate_native_seasons(path, definition, season, inventory)
    elif any(g['source_kind'] != 'setup' for g in inventory.get('source_grants', [])):
        raise ValueError('Source pack account lacks source journal')
    if (path / 'first-run-completion.json').exists():
        from .first_run_account import inspect as inspect_setup
        inspect_setup(path)
    elif any(g['source_kind'] == 'setup' for g in inventory.get('source_grants', [])):
        raise ValueError('Welcome packs lack setup receipt')
    return {
        'persona_id': p.persona_id, 'identity_pid': p.identity_pid, 'user_id': p.user_id,
        'credits': p.credits, 'fifa_points': p.fifa_points,
        'division': definition.division_index,
        'season_round': season.round_number if season else None,
        'unopened_pack_ids': [r['catalog_id'] for r in inventory['entitlements']],
    }


def validate_native_seasons(path, definition, season, inventory):
    from .native_season_completion import NativeSeasonCoordinator
    # This copy is private/quiescent; inspect only, never recover or write.
    state = NativeSeasonCoordinator(path, enabled=True)._load()
    if state['prepared'] is not None or state['active_match'] is not None:
        raise ValueError('Finish/recover active native transaction before coherent backup')
    cycle = state['cycle']
    if cycle['division'] != definition.division_index:
        raise ValueError('Native cycle/definition conflict')
    if cycle['status'] == 'active':
        if season is None:
            raise ValueError('Active native cycle lacks original season state')
        last = next((m for m in reversed(state['matches']) if m['cycle_id'] == cycle['id']), None)
        if last and (season.round_number, season.user_points) != (last['fixture'] + 1, last['points_after']):
            raise ValueError('Original native save still pending or conflicting')
    elif season is not None:
        raise ValueError('Pending next cycle already has unobserved season state')
    for grant in inventory.get('source_grants', []):
        if grant['policy_version'] in ('tournament_rewards_v2', 'level_rewards_v1', 'accomplishments_v1', 'first_run_v1'):
            continue  # owned by the tournament ledger / level receipt / accomplishment claim
        collection = state['matches'] if grant['source_kind'] == 'fixture' else state['completions']
        source = next((s for s in collection if s['id'] == grant['source_id']), None)
        legacy = grant['policy_version'] == 'backend_pack_entitlement_test_v1'
        if (source is None or source['cycle_id'] != grant['cycle_id']
                or grant['account_id'] != state['account_id']
                or (legacy and source.get('pack_entitlement_policy_version') != grant['policy_version'])):
            raise ValueError('Pack reward source owner conflict')


def validate_domains(path):
    """Read-only checks for the stores added after the first backup schema."""
    path = Path(path)
    result = {}
    packs = json.loads((path / 'packs.json').read_bytes())
    unopened = {e['catalog_id'] for e in packs['entitlements']}
    receipts = json.loads((path / 'purchases.json').read_bytes())['receipts']
    from .store_direct_delivery import is_direct
    if any(is_direct(r) and r['entitlement']['catalog_id'] in unopened for r in receipts):
        raise ValueError('Recover interrupted direct delivery before backup')
    if (path / 'market.json').exists():
        from . import market_store
        market = market_store.load(path)
        result['market'] = {
            'next_trade_id': market['next_trade_id'],
            'listings': len(market['listings']),
        }
    if (path / 'pack-sessions.json').exists():
        result['pack_sessions'] = validate_pack_sessions(path, receipts)
    if (path / 'item-history.json').exists():
        from .item_history import validate_file
        validate_file(path)
    if (path / 'accomplishments.json').exists():
        from .accomplishments import validate_file as validate_accomplishments
        validate_accomplishments(path)
    if (path / 'draw-history-seal.json').exists():
        from .draw_seal import records as sealed_records
        result['draw_history_seal'] = {k: len(v) for k, v in sealed_records(path).items()}
    if (path / 'player-exchanges.json').exists():
        from .player_exchange import PlayerExchangeCoordinator
        exchange = PlayerExchangeCoordinator(path, policy_path=EXCHANGE_POLICY, enabled=True)
        value = exchange.inspect()
        result['player_exchanges'] = {'receipts': len(value['receipts']), 'active': value['active']}
    if any(path.glob('native-tournament*.json')):
        result['tournaments'] = validate_tournaments(path)
    return result


def validate_tournaments(path):
    from .native_tournament_match import ledger
    from .native_tournament_state import CUPS, path_for
    value = ledger(path)
    if value.get('prepared') is not None:
        raise ValueError('Recover pending tournament result before backup')
    cups = []
    for cup in CUPS:
        file = path_for(path, cup)
        if file.exists():
            state = json.loads(file.read_bytes())
            if type(state) is not dict or state.get('tournament_id') != cup:
                raise ValueError('Tournament file/cup mismatch')
            cups.append(cup)
    return {'active': value['active'] is not None, 'cups': cups}


def validate_pack_sessions(path, receipts):
    from . import native_pack_sessions as sessions
    value = json.loads((path / 'pack-sessions.json').read_bytes())
    if set(value) != {'version', 'epochs'} or value['version'] != sessions.VERSION:
        raise ValueError('Invalid pack sessions')
    known = set()
    for number, epoch in enumerate(value['epochs'], 1):
        if (type(epoch) is not dict or epoch.get('number') != number
                or epoch.get('sid') != sessions.sid(epoch.get('code', ''))):
            raise ValueError('Invalid pack epoch')
        known.add(epoch['sid'])
    if any('session_id' in r and r['session_id'] not in known for r in receipts):
        raise ValueError('Pack session metadata missing or rolled back')
    return {'epochs': len(value['epochs'])}


def selector_accounts(path):
    """Account path each release selector was admitted for (None if unbound).

    Selectors copied from another account stay inactive there; they are kept
    byte-for-byte and reported, never rewritten.
    """
    result = {}
    for name in sorted(SELECTORS):
        file = Path(path) / name
        if not file.exists():
            continue
        value = json.loads(file.read_bytes())
        if type(value) is not dict or 'version' not in value:
            raise ValueError('Invalid release selector: ' + name)
        account = value.get('account')
        if account is not None and type(account) is not str:
            raise ValueError('Invalid release selector account: ' + name)
        result[name] = account
    return result


def create_backup(source, destination, *, quiescent=False):
    if quiescent is not True:
        raise ValueError('Explicit quiescent-writer assertion required')
    source = Path(source).resolve()
    destination = safe_destination(destination)
    account_files(source)
    if source == destination or source in destination.parents:
        raise ValueError('Separate backup destination required')
    require_stopped(source)
    # Existing flock identities only: backup never creates lock files in source.
    # Market/pack-session writers have no file lock; require_stopped covers them.
    with ExitStack() as stack:
        for name in LOCK_ORDER:
            lock = source / (name + '.lock')
            if lock.exists():
                if lock.is_symlink():
                    raise ValueError('Lock alias refused')
                handle = stack.enter_context(lock.open('rb'))
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        manifest = snapshot(source, destination)
        lab = source / SNAPSHOT_MANIFEST
        lab_digest = None
        if lab.is_file() and not lab.is_symlink():
            (destination / LAB_MANIFEST_COPY).write_bytes(lab.read_bytes())
            lab_digest = file_digest(destination / LAB_MANIFEST_COPY)
    metadata = {
        'schema': SCHEMA, 'kind': 'offline_fut_lab_backup', 'utc': now(),
        'account': validate_account(destination),
        'domains': validate_domains(destination),
        'source': str(source),
        'root': str(ROOT),
        'selector_accounts': selector_accounts(destination),
        'lab_snapshot': lab_digest,
        'files': manifest['sha256'],
        'coherence': 'Stopped backend, quiescent assertion, existing locks, two identical reads '
                     'and complete store/source validation.',
        'resources': 'External supplied resources referenced, never bundled here.',
    }
    new_json(destination / MANIFEST, metadata)
    return metadata


def verified_backup(backup):
    """Load and fully re-validate a backup before any destination write."""
    backup = Path(backup).resolve()
    metadata = json.loads((backup / MANIFEST).read_text())
    if (type(metadata) is not dict or metadata.get('schema') not in MANIFEST_KEYS
            or type(metadata['schema']) is not int
            or set(metadata) != MANIFEST_KEYS[metadata['schema']]
            or metadata['kind'] != 'offline_fut_lab_backup'):
        raise ValueError('Unsupported backup manifest')
    actual = account_files(backup)
    if set(actual) != set(metadata['files']) or any(
            file_digest(backup / name) != digest for name, digest in metadata['files'].items()):
        raise ValueError('Backup files/hash mismatch')
    if validate_account(backup) != metadata['account']:
        raise ValueError('Backup account identity/summary mismatch')
    if metadata['schema'] >= 2:
        if (validate_domains(backup) != metadata['domains']
                or selector_accounts(backup) != metadata['selector_accounts']):
            raise ValueError('Backup domain summary mismatch')
        lab = backup / LAB_MANIFEST_COPY
        digest = file_digest(lab) if lab.is_file() else None
        if digest != metadata['lab_snapshot']:
            raise ValueError('Backup lab manifest mismatch')
    return backup, metadata


def restore_backup(backup, destination):
    """Restore into a NEW reports/.../isolated-account for inspection."""
    backup, metadata = verified_backup(backup)
    destination = safe_destination(destination)
    # No writes to backup/source; new destination snapshot preserves all JSON bytes.
    copied = create_backup(backup, destination, quiescent=True)
    if copied['files'] != metadata['files'] or copied['account'] != metadata['account']:
        raise ValueError('Restored account differs from certified backup')
    bound = metadata.get('selector_accounts', {})
    copied['active_selectors'] = sorted(n for n, a in bound.items() if a == str(destination))
    return copied


def account_destination(destination):
    """The normal account or a reports/.../isolated-account that does not exist yet."""
    destination = Path(destination)
    if destination.is_symlink():
        raise ValueError('Account destination alias refused')
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError('Set the current account aside before restoring')
    if destination != REAL:
        safe_destination(destination)
    if not destination.parent.is_dir():
        raise ValueError('Account parent directory missing')
    return destination


def recorded_root(metadata):
    """Project folder the backup was taken in (derived for schema 2)."""
    if 'root' in metadata:
        return metadata['root']
    for marker in ('/server/data/development/', '/reports/'):
        if marker in metadata['source']:
            return metadata['source'].split(marker)[0]
    return None


def rebound(raw, source, destination, old_root=None):
    """Selector bytes moved to this account and this project folder.

    The source account path becomes the destination. Any other path inside the
    old project folder (archives, certificates) moves to the current project
    folder. Paths outside the project are left as they are.
    """
    new_root = str(ROOT)

    def move(item):
        if isinstance(item, dict):
            return {k: move(v) for k, v in item.items()}
        if isinstance(item, list):
            return [move(v) for v in item]
        if isinstance(item, str):
            if item == source:
                return destination
            if old_root and old_root != new_root and item.startswith(old_root + '/'):
                return new_root + item[len(old_root):]
        return item
    value = json.loads(raw)
    moved = move(value)
    if moved == value:
        return raw
    return (json.dumps(moved, indent=2) + '\n').encode()


def stamp():
    return now().replace(':', '').replace('-', '').split('.')[0]


def import_account(backup, destination):
    """Place a verified backup at a (not yet existing) account path.

    Same path: byte-for-byte, with the account's own lab marker. Another path:
    selectors that named the source are rebound to the destination; selectors
    copied from elsewhere stay as they are. Staged, hash-checked, then renamed.
    """
    backup, metadata = verified_backup(backup)
    if metadata['schema'] < 2:
        raise ValueError('Backup does not record its source account')
    destination = account_destination(destination)
    source = metadata['source']
    staging = destination.with_name(destination.name + '.restoring')
    if staging.exists():
        raise FileExistsError('Earlier interrupted restore staging retained: ' + str(staging))
    staging.mkdir()
    rebinds = []
    for name in metadata['files']:
        raw = (backup / name).read_bytes()
        if name in SELECTORS:
            new = rebound(raw, source, str(destination), recorded_root(metadata))
            if new != raw:
                rebinds.append(name)
            raw = new
        (staging / name).write_bytes(raw)
    if any(file_digest(staging / n) != d for n, d in metadata['files'].items() if n not in rebinds):
        raise ValueError('Staged restore differs from backup; staging retained')
    lab = backup / LAB_MANIFEST_COPY
    if str(destination) == source and lab.is_file():
        (staging / SNAPSHOT_MANIFEST).write_bytes(lab.read_bytes())
    elif destination != REAL:
        # Isolated accounts need their own lab marker describing these bytes.
        files = {n: file_digest(staging / n) for n in metadata['files']}
        (staging / SNAPSHOT_MANIFEST).write_text(json.dumps(
            {'source': str(backup), 'utc': now(), 'sha256': files}, indent=2) + '\n')
    # The backup itself was fully validated above; byte identity is the proof.
    # Re-validating in place is wrong for evolved lab accounts, whose original
    # .lab-snapshot.json no longer matches their current files.
    os.rename(staging, destination)
    return {'restored': str(destination), 'source': source, 'rebound': sorted(rebinds),
            'files': metadata['files'], 'account': metadata['account'],
            'domains': metadata['domains'], 'utc': now()}


def restore_original(backup, destination):
    """Recreate the account byte-for-byte at the path it was backed up from."""
    _, metadata = verified_backup(backup)
    if metadata['schema'] < 2:
        raise ValueError('Backup does not record its original account')
    if str(Path(destination).resolve()) != metadata['source']:
        raise ValueError('Original restore must target the account the backup was taken from')
    return import_account(backup, destination)


def set_aside(account, *, label='set-aside'):
    """Rename an account to a dated sibling; never delete it."""
    account = Path(account)
    if account.is_symlink() or not account.is_dir():
        raise ValueError('Existing account directory required')
    account = account.resolve()
    if account != REAL and (ROOT / 'reports' not in account.parents or account.name != 'isolated-account'):
        raise ValueError('Only reports/.../isolated-account or the normal account')
    require_stopped(account)
    target = account.with_name(account.name + '.' + label + '-' + stamp())
    if target.exists():
        raise FileExistsError(target)
    os.rename(account, target)
    return target
