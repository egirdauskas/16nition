"""Direct current runtime for completed first-run accounts, explicitly selected.

Historical deployment and migration markers are deliberately separate. This
profile binds the new account owner and current configuration; existing purchase,
opening and native match journals still own every transaction and recovery.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from .account_transaction import atomic
from .policy_memo import fingerprint, policy_memo

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'server/policy/fresh-account-runtime-v1.json'
MARKER = 'account-runtime.json'
VERSION = 'fresh_account_runtime_v1'
ACCOUNT = None
SELECTOR_SHA = None
FILES = ('profile.json', 'football.json', 'content.json', 'packs.json',
         'seasons.json', 'definition.json', 'control.json')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def ordinary(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError('Fresh runtime requires independent regular account files')
    return path.read_bytes()


class StaleRuntimePolicy(ValueError):
    """The club's recorded Store policy/catalog no longer matches the runtime.

    Such a club cannot start, so it cannot hold an active session; switching
    away from it is safe. It is never repaired or rebound automatically.
    """


@policy_memo
def policy():
    value = json.loads(PATH.read_bytes())
    if (value.get('version') != VERSION or value.get('classification') != 'revival_policy'
            or value.get('default_enabled') is not False
            or value.get('new_account_store') != 'latest_approved_catalog_directly'
            or value.get('sealing') != 'only_for_new_specials_or_changed_odds'
            or len(value['flags']) != len(set(value['flags']))
            or any(not flag.startswith('--') for flag in value['flags'])
            or any(Path(name).name != name for name in value['policies'].values())):
        raise ValueError('Unknown fresh-account runtime policy')
    return value


@policy_memo
def current_catalog_bytes():
    from .store_single_consumables import catalog
    return encode(catalog())


@lru_cache(maxsize=32)
def _validated(raw, setup_raw, profile_raw, catalog_raw, current_catalog, policy_hash):
    value = json.loads(raw)
    from .first_run_account import _validate_receipt
    setup = _validate_receipt(setup_raw)
    profile = json.loads(profile_raw)
    required = {'version', 'account', 'account_id', 'setup_receipt_sha256',
                'policy_sha256', 'catalog_sha256', 'policy_fingerprint',
                'initial_catalog_id', 'verification'}
    if (set(value) != required or value['version'] != VERSION
            or value['verification'] != 'manual_end_to_end_pending'
            or value['account_id'] != setup['account_id']
            or value['setup_receipt_sha256'] != sha(setup_raw)
            or value['catalog_sha256'] != sha(catalog_raw)
            or type(value['initial_catalog_id']) is not int
            or not 30001 <= value['initial_catalog_id'] <= 65535):
        raise ValueError('Fresh runtime owner or current Store policy changed')
    if (value['policy_sha256'] != sha(PATH.read_bytes())
            or value['policy_fingerprint'] != policy_hash
            or json.loads(catalog_raw) != json.loads(current_catalog)):
        raise StaleRuntimePolicy('Fresh runtime owner or current Store policy changed')
    for key in ('persona_id', 'identity_pid', 'user_id'):
        if profile[key] != setup[key]:
            raise ValueError('Fresh runtime profile identity differs from setup')
    return value


def validate(account):
    account = Path(account)
    if account.is_symlink() or account.resolve() == ROOT / 'server/data/development/fm16in2026':
        raise ValueError('Fresh runtime cannot adopt the preserved development account')
    account = account.resolve()
    from .first_run_account import RECEIPT
    value = _validated(
        ordinary(account / MARKER), ordinary(account / RECEIPT),
        ordinary(account / 'profile.json'), ordinary(account / 'products.json'),
        current_catalog_bytes(), fingerprint().hex(),
    )
    if value['account'] != str(account):
        raise ValueError('Fresh runtime selector belongs to another account')
    return deepcopy(value)


def marker_sha(account):
    return sha(ordinary(Path(account) / MARKER))


def selected(account):
    if ACCOUNT is None or account is None or Path(account).resolve() != ACCOUNT:
        return False
    if marker_sha(ACCOUNT) != SELECTOR_SHA:
        raise ValueError('Fresh runtime selector changed during the session')
    validate(ACCOUNT)
    return True


def configure(account=None):
    global ACCOUNT, SELECTOR_SHA
    ACCOUNT = SELECTOR_SHA = None
    if account is None:
        return
    account = Path(account).resolve()
    validate(account)
    ACCOUNT, SELECTOR_SHA = account, marker_sha(account)


def configure_arguments(args, parser):
    """Require one complete current composition, never a partial feature mix."""
    configure()
    if args.account_runtime_profile is None:
        return False
    if args.profile_state is None:
        raise ValueError('Fresh profile needs its explicit account selectors')
    account = args.profile_state.resolve().parent
    if args.account_runtime_profile.is_symlink() or args.account_runtime_profile.resolve() != account / MARKER:
        raise ValueError('Fresh profile must belong to the selected account')
    try:
        configure(account)
        validate_selectors([args.profile_state, args.football_state, args.football_catalog,
                            args.revival_pack_state, args.offline_seasons_state,
                            args.offline_seasons_definition, args.startup_control])
        current = policy()
        for flag in current['flags']:
            action = parser._option_string_actions[flag]
            expected = action.const
            chosen = getattr(args, action.dest)
            if type(chosen) is not type(expected) or chosen != expected:
                raise ValueError('Fresh profile requires ' + flag)
        for flag, name in current['policies'].items():
            chosen = getattr(args, parser._option_string_actions[flag].dest)
            if chosen is None or chosen.resolve() != PATH.parent / name:
                raise ValueError('Fresh profile requires the current policy for ' + flag)
        incompatible = (
            'gameplay_release', 'store_release', 'reward_release', 'season_choice_release',
            'native_source_pack_presentation', 'profile_plate_projection',
            'native_played_matches', 'market_empty_control',
            'pack_catalog_empty_control', 'store_product_overlay',
        )
        if any(getattr(args, name, None) for name in incompatible):
            raise ValueError('Fresh profile excludes historical releases and experimental projections')
        ensure_current_features(account)
    except Exception:
        configure()
        raise
    return True


def ensure_current_features(account):
    """Select the approved current features; never copy another account's history."""
    from .accomplishments import ensure_enabled
    from . import market_supply_big5, market_supply_scale
    validate(account)
    for module in (market_supply_big5, market_supply_scale):
        path = Path(account) / module.MARKER
        if path.exists() or path.is_symlink():
            ordinary(path)
            if not module.enabled(account):
                raise ValueError('Fresh Market selector belongs to another account')
        else:
            atomic(path, encode(module.marker_for(account)))
    ensure_enabled(account)


def validate_selectors(paths):
    if len(paths) != len(FILES) or any(path is None for path in paths):
        raise ValueError('Fresh runtime requires all account selectors')
    paths = [Path(path) for path in paths]
    account = paths[0].resolve().parent
    if not selected(account) or any(
        path.is_symlink() or path.name != name or path.resolve().parent != account
        for path, name in zip(paths, FILES)
    ):
        raise ValueError('Fresh runtime selectors must share the configured account')
    return account


def documents(account):
    """Provision current configuration only; no grant, seal or old Store upgrade."""
    account = Path(account).resolve()
    from .first_run_account import inspect, RECEIPT
    from .first_run_catalog import initial_store, initial_control
    from .local_packs import PackStore
    from .native_pack_sessions import PRIVATE_VERSION
    setup = inspect(account)
    if account == ROOT / 'server/data/development/fm16in2026':
        raise ValueError('Never provision over the preserved development account')
    if (account / MARKER).exists():
        validate(account)
        return {}
    packs = PackStore(account / 'packs.json').load()
    purchases = json.loads(ordinary(account / 'purchases.json'))
    # This direct path admits a newly constructed club, not a historic account
    # whose old Store/caption lineage would need separate preservation work.
    if (packs.get('prepared') or purchases.get('prepared') or purchases['receipts']
            or any(g['source_kind'] != 'setup' for g in packs.get('source_grants', []))
            or packs.get('voucher_grants')):
        raise ValueError('Initial fresh runtime needs a quiescent setup-only pack store')
    season_path = account / 'native-seasons.json'
    if season_path.exists():
        seasons = json.loads(ordinary(season_path))
        if seasons.get('active_match') or seasons.get('prepared') or seasons['matches'] or seasons['completions']:
            raise ValueError('Fresh runtime cannot replace an existing gameplay configuration')
    value = initial_store(account)
    value['packs.json'] = {**packs, 'identity_version': PRIVATE_VERSION}
    control = initial_control()
    control.update(inventory='pass', squad_management='pass')
    value['control.json'] = control
    from .level_rewards import marker_for as level_marker
    from .store_direct_delivery import marker_for as delivery_marker
    value['level-rewards.json'] = level_marker(account)
    value['store-direct-delivery.json'] = delivery_marker(account)
    value[MARKER] = {
        'version': VERSION, 'account': str(account), 'account_id': setup['account_id'],
        'setup_receipt_sha256': sha(ordinary(account / RECEIPT)),
        'policy_sha256': sha(PATH.read_bytes()),
        'catalog_sha256': sha(encode(value['products.json'])),
        'policy_fingerprint': fingerprint().hex(),
        'initial_catalog_id': packs['next_catalog_id'],
        'verification': 'manual_end_to_end_pending',
    }
    return value


def prepare(account):
    """Recoverable configuration installation, profile written last.

    Call only with the client stopped and an independent account backup. An
    interrupted installation can be retried; wallet, owned items, receipts and
    the pack allocator never advance. The final profile is the activation barrier.
    """
    account = Path(account).resolve()
    values = documents(account)
    for name, value in values.items():
        atomic(account / name, encode(value))
    validate(account)
    ensure_current_features(account)
    return account / MARKER


def argv(account, *, port=18081, output=None):
    account = Path(account).resolve()
    validate(account)
    value = policy()
    result = ['python3', str(ROOT / 'server/reachability.py'), '--output',
              str(output or ROOT / 'captures/reachability.jsonl'), '--port', str(port),
              '--persona-id', '1', '--account-runtime-profile', str(account / MARKER)]
    names = {
        '--profile-state': 'profile.json', '--football-state': 'football.json',
        '--football-catalog': 'content.json', '--revival-pack-state': 'packs.json',
        '--offline-seasons-state': 'seasons.json', '--offline-seasons-definition': 'definition.json',
        '--startup-control': 'control.json',
    }
    for flag, name in names.items():
        result.extend((flag, str(account / name)))
    result.extend(value['flags'])
    for flag, name in value['policies'].items():
        result.extend((flag, str(PATH.parent / name)))
    return result


HISTORY = 'account-runtime-history.json'
HISTORY_VERSION = 'fresh_account_runtime_history_v1'


def stale(account):
    """True when only the recorded Store policy/catalog pins are out of date."""
    try:
        validate(account)
    except StaleRuntimePolicy:
        return True
    return False


def _quiescent(account):
    from .local_packs import PackStore
    packs = PackStore(account / 'packs.json').load()
    purchases = json.loads(ordinary(account / 'purchases.json'))
    if packs.get('prepared') or purchases.get('prepared'):
        raise ValueError('Finish or recover the pending pack/purchase before updating the club')
    season_path = account / 'native-seasons.json'
    if season_path.exists():
        seasons = json.loads(ordinary(season_path))
        if seasons.get('active_match') or seasons.get('prepared'):
            raise ValueError('Finish or recover the active match before updating the club')


def _feature_markers():
    """Per-club selectors that pin one server/policy file's SHA-256."""
    from . import (accomplishments, level_rewards, market_supply_big5, market_supply_scale,
                   store_demo_offers, store_direct_delivery)
    return ((level_rewards.MARKER, level_rewards), (market_supply_big5.MARKER, market_supply_big5),
            (market_supply_scale.MARKER, market_supply_scale),
            (store_demo_offers.MARKER, store_demo_offers),
            (store_direct_delivery.MARKER, store_direct_delivery),
            (accomplishments.SELECTOR, accomplishments))


def _repin_feature_markers(account):
    """Re-pin this club's existing feature selectors to the current policies only."""
    repinned = []
    for name, module in _feature_markers():
        path = account / name
        if not path.exists():
            continue
        old = json.loads(ordinary(path))
        new = module.marker_for(account)
        if set(old) != set(new) or old['account'] != str(account) or old['version'] != new['version']:
            raise ValueError('Feature selector belongs to another account or version: ' + name)
        if old != new:
            atomic(path, encode(new))
            repinned.append(name)
    return repinned


def _snapshot(account, snapshot_root):
    """Byte-exact pre-update copy with a SHA-256 manifest (club must be stopped)."""
    import datetime
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = Path(snapshot_root) / ('club-update-' + stamp)
    copies = destination / 'files'  # accounts have their own manifest.json
    copies.mkdir(parents=True)
    files = {}
    for path in sorted(account.iterdir()):
        if path.is_symlink() or path.is_dir():
            raise ValueError('Unexpected account entry: ' + path.name)
        raw = path.read_bytes()
        (copies / path.name).write_bytes(raw)
        files[path.name] = sha(raw)
    manifest = {'account': str(account), 'files': files}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    return destination, files


def _rollback(account, snapshot, files):
    for path in account.iterdir():
        if path.name not in files:
            path.unlink()
    for name, digest in files.items():
        raw = (snapshot / 'files' / name).read_bytes()
        if sha(raw) != digest:
            raise ValueError('Pre-update snapshot changed; restore manually from ' + str(snapshot))
        atomic(account / name, raw)


def readmit(account, snapshot_root):
    """Bring a stale-policy club to the current runtime policy, explicitly.

    Only the Store catalog (fresh clubs use the latest approved catalog) and the
    runtime marker's policy/catalog pins change, plus current feature markers.
    Owner identity, wallet, items, receipts, seals and seasons are never
    rewritten. A byte-exact snapshot is taken first and restored on any
    validation failure; each update is appended to account-runtime-history.json.
    """
    from .account_backup import require_stopped, validate_account
    from .first_run_catalog import initial_store
    account = Path(account).resolve()
    if account == ROOT / 'server/data/development/fm16in2026':
        raise ValueError('Never update the preserved development account')
    if not stale(account):
        raise ValueError('Club is already current')
    require_stopped(account)
    _quiescent(account)
    old = json.loads(ordinary(account / MARKER))
    snapshot, files = _snapshot(account, snapshot_root)
    try:
        products = initial_store(account)['products.json']
        atomic(account / 'products.json', encode(products))
        marker = dict(old)
        marker.update(policy_sha256=sha(PATH.read_bytes()),
                      policy_fingerprint=fingerprint().hex(),
                      catalog_sha256=sha(encode(products)))
        atomic(account / MARKER, encode(marker))
        repinned = _repin_feature_markers(account)
        validate(account)
        ensure_current_features(account)
        configure(account)
        validate_account(account)
        history_path = account / HISTORY
        history = (json.loads(ordinary(history_path)) if history_path.exists()
                   else {'version': HISTORY_VERSION, 'updates': []})
        if history.get('version') != HISTORY_VERSION:
            raise ValueError('Unknown club update history')
        history['updates'].append({
            'from_policy_fingerprint': old['policy_fingerprint'],
            'to_policy_fingerprint': marker['policy_fingerprint'],
            'from_catalog_sha256': old['catalog_sha256'],
            'to_catalog_sha256': marker['catalog_sha256'],
            'repinned_feature_selectors': repinned,
            'snapshot': str(snapshot),
            'snapshot_manifest_sha256': sha((snapshot / 'manifest.json').read_bytes()),
        })
        atomic(history_path, encode(history))
    except BaseException:
        configure()
        _rollback(account, snapshot, files)
        raise
    return {'account': str(account), 'snapshot': str(snapshot),
            'policy_fingerprint': marker['policy_fingerprint']}
