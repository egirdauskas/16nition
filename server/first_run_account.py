"""FIRST-001 new-account construction; no implicit login grants or new wire path.

Build all initial domains privately and publish one complete directory. Recovery
uses the existing durable image writer; the creation receipt replaces the bulky
prepared images before publication. Existing accounts are never seeded again.
"""
from copy import deepcopy
from dataclasses import asdict, replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import uuid

from .account_transaction import atomic
from .policy_memo import policy_memo

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'server/policy/first-run-v1.json'
RECEIPT = 'first-run-completion.json'
VERSION = 'first_run_v1'
BASE_FILES = {
    'profile.json', 'football.json', 'content.json', 'packs.json', 'purchases.json',
    'products.json', 'seasons.json', 'definition.json', 'definition-response.json',
    'no-current-response.json', 'control.json', 'manifest.json',
    'welcome-gift.json', 'first-run.json',
}
FILES = BASE_FILES | {'store-demo-offers.json'}
_RECEIPT_CACHE = {}
_SESSION_CACHE = {}


def _profile(creation_id, name=None, abbreviation=None, credits=0):
    from .local_profile import LocalProfile
    owner = uuid.uuid5(uuid.UUID(creation_id), 'account')
    identity = int.from_bytes(owner.bytes[4:12], 'big') & 0x7fffffffffffffff or 1
    return LocalProfile(identity, 1, uuid.uuid5(owner, 'user').hex,
                        uuid.uuid5(owner, 'victory-token').hex, credits=credits,
                        club_name=name, division_offline=10, revival_total_xp=0,
                        club_abbreviation=abbreviation)


def session_path(account):
    account = Path(account).absolute()
    return account.with_name('.' + account.name + '.first-run-session.json')


def begin_setup(destination, *, creation_id):
    """Reserve an isolated identity, without creating an account or awarding it.

    This opt-in session sits OUTSIDE the eventual account directory. Existing
    read stores can report empty ownership while the original creation UI runs;
    CreateUser will publish the complete directory at those same store paths.
    """
    destination = Path(destination).absolute()
    if destination.is_symlink() or destination.resolve() != destination or destination.exists():
        raise FileExistsError('First-run setup needs a new account destination')
    creation_id = str(uuid.UUID(creation_id))
    destination.parent.mkdir(parents=True, exist_ok=True)
    path = session_path(destination)
    value = {'version': 'first_run_session_v1', 'account': str(destination),
             'creation_id': creation_id}
    lock_path = destination.with_name('.' + destination.name + '.creation.lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if destination.exists():
            raise FileExistsError('First-run account already exists')
        if path.is_symlink():
            raise ValueError('Setup session alias refused')
        if path.exists():
            existing = pending_session(destination)
            if {key: existing[key] for key in value} != value:
                raise ValueError('Existing setup session has different inputs')
            return existing
        else:
            atomic(path, encode(value))
    return value


def pending_session(account):
    account = Path(account).absolute()
    path = session_path(account)
    if account.exists() or not path.is_file():
        return None
    if path.is_symlink() or account.resolve() != account:
        raise ValueError('Setup session alias refused')
    raw = path.read_bytes()
    key = digest(raw)
    if key not in _SESSION_CACHE:
        value = json.loads(raw)
        if (set(value) - {'favorite_team_id', 'favorite_country_id', 'favorite_player_id'} != {'version', 'account', 'creation_id'}
                or value['version'] != 'first_run_session_v1'):
            raise ValueError('Invalid first-run session')
        uuid.UUID(value['creation_id'])
        if value.get('favorite_team_id') is not None:
            from .season_content import eligible_team_ids
            if type(value['favorite_team_id']) is not int or value['favorite_team_id'] not in eligible_team_ids():
                raise ValueError('Unknown supplied favourite club')
        from .favorites import valid_country, valid_player
        if (not valid_country(value.get('favorite_country_id'))
                or not valid_player(value.get('favorite_player_id'))):
            raise ValueError('Unknown supplied favourite country/player')
        if len(_SESSION_CACHE) >= 32:
            _SESSION_CACHE.clear()
        _SESSION_CACHE[key] = value
    value = deepcopy(_SESSION_CACHE[key])
    if value['account'] != str(account):
        raise ValueError('Foreign setup session')
    return value


def pending_profile(path):
    path = Path(path).absolute()
    if path.name != 'profile.json':
        return None
    value = pending_session(path.parent)
    if value is None:
        return None
    return replace(_profile(value['creation_id']), favorite_team_id=value.get('favorite_team_id'),
                   favorite_country_id=value.get('favorite_country_id'),
                   favorite_player_id=value.get('favorite_player_id'))


def save_favorite_team(account, team_id):
    from .season_content import eligible_team_ids
    if type(team_id) is not int or team_id not in eligible_team_ids():
        raise ValueError('Unknown supplied favourite club')
    return save_preferences(account, {'favorite_team_id': team_id})


def save_preferences(account, changes):
    from .favorites import valid_country, valid_player
    from .season_content import eligible_team_ids
    if set(changes) - {'favorite_team_id', 'favorite_country_id', 'favorite_player_id'}:
        raise ValueError('Unknown setup preferences')
    team = changes.get('favorite_team_id')
    if (team is not None and (type(team) is not int or team not in eligible_team_ids())
            or not valid_country(changes.get('favorite_country_id'))
            or not valid_player(changes.get('favorite_player_id'))):
        raise ValueError('Unknown supplied setup preference')
    account = Path(account).absolute()
    lock_path = account.with_name('.' + account.name + '.creation.lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        value = pending_session(account)
        if value is None:
            raise ValueError('No pending setup identity')
        if any(value.get(key) != item for key, item in changes.items()):
            if account.with_name('.' + account.name + '.creating').exists():
                raise ValueError('Recover prepared club creation before editing preferences')
            value.update(changes)
            atomic(session_path(account), encode(value))
    return value


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


@policy_memo
def policy():
    from .welcome_gift import policy as welcome_policy
    value = json.loads(POLICY.read_bytes())
    if value['classification'] != 'revival_policy' or value['version'] != VERSION:
        raise ValueError('Unknown first-run policy')
    starter = value['starter_inventory']
    if (starter['bronze_roster']['count'] != 18 or starter['manager_count'] != 1
            or starter['extra_club_item_bundle'] is not False
            or starter['extra_players'] != [
                {'count': 1, 'tier': 'gold', 'rarity': 'non_rare', 'selection': 'random'},
                {'count': 3, 'tier': 'silver', 'selection': 'random'}]):
        raise ValueError('Unsupported first-run starter specification')
    grant = welcome_policy()['grant']
    if (grant['coins'] != 7500 or grant['packs']['count'] != 5
            or value['welcome_gift']['coins'] != grant['coins']
            or value['welcome_gift']['premium_gold_packs'] != grant['packs']['count']
            or grant['packs']['untradeable'] is not True):
        raise ValueError('First-run and welcome policies disagree')
    return value


def allowed_pack_definitions():
    from .welcome_gift import policy as welcome_policy
    return {welcome_policy()['grant']['packs']['definition']}


def validate_identity(name, abbreviation):
    # The shipped NameYourClub and EditAcronymPopup use the same bounds.
    if (type(name) is not str or not name.isascii() or name != name.strip()
            or not 5 <= len(name) <= 15 or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or type(abbreviation) is not str or not abbreviation.isascii()
            or len(abbreviation) != 3 or abbreviation != abbreviation.strip().upper()
            or any(ord(c) < 32 or ord(c) == 127 for c in abbreviation)):
        raise ValueError('Invalid original club name/abbreviation')


def _validate_receipt(raw):
    value = json.loads(raw)
    if (type(value) is not dict or value.get('version') != VERSION
            or value.get('status') != 'complete'):
        raise ValueError('Incomplete first-run account')
    creation = uuid.UUID(value['creation_id'])
    if value['account_id'] != str(uuid.uuid5(creation, 'account')):
        raise ValueError('First-run account owner conflict')
    validate_identity(value['club_name'], value['club_abbreviation'])
    if (value['persona_id'] != 1 or value['credits_granted'] != 7500
            or len(value['pack_grants']) != 5
            or len(set(value['pack_grants'])) != 5
            or type(value['files']) is not dict or set(value['files']) not in (BASE_FILES, FILES)
            or any(type(h) is not str or len(h) != 64
                   or any(c not in '0123456789abcdef' for c in h) for h in value['files'].values())):
        raise ValueError('Invalid first-run grant receipt')
    for ordinal, reward_id in enumerate(value['pack_grants']):
        source = uuid.uuid5(creation, 'welcome-pack:%d' % ordinal)
        if reward_id != str(uuid.uuid5(source, 'setup-pack')):
            raise ValueError('Invalid first-run reward source')
    return value


def receipt(account):
    raw = (Path(account) / RECEIPT).read_bytes()
    key = digest(raw)
    if key not in _RECEIPT_CACHE:
        value = _validate_receipt(raw)
        if len(_RECEIPT_CACHE) >= 32:
            _RECEIPT_CACHE.clear()
        _RECEIPT_CACHE[key] = value
    return deepcopy(_RECEIPT_CACHE[key])


def account_id(account):
    path = Path(account) / RECEIPT
    return receipt(account)['account_id'] if path.exists() else None


def inspect(account):
    """Validate source ownership without requiring initial wallet/items unchanged."""
    from .local_profile import load_profile
    from .local_packs import PackStore
    account = Path(account)
    value = receipt(account)
    profile = load_profile(account / 'profile.json')
    if (profile.identity_pid != value['identity_pid'] or profile.persona_id != 1
            or profile.user_id != value['user_id']):
        raise ValueError('First-run profile ownership conflict')
    packs = PackStore(account / 'packs.json').load(1)
    grants = [g for g in packs.get('source_grants', []) if g['source_kind'] == 'setup']
    if ({g['reward_id'] for g in grants} != set(value['pack_grants'])
            or len(grants) != 5 or any(g['account_id'] != value['account_id'] for g in grants)):
        raise ValueError('First-run pack ownership conflict')
    return value


def _images(name, abbreviation, creation_id, destination):
    from .first_run_roster import starter_roster
    from .local_football import FootballStore, validate
    from .local_content import ContentCatalog
    from .local_packs import PackStore
    from .local_seasons import load_definition
    from .offline_seasons_protocol import definition_response
    from .welcome_gift import policy as welcome_policy
    from .welcome_gift import SELECTOR_VERSION
    policy()
    creation = uuid.UUID(creation_id)
    owner = uuid.uuid5(creation, 'account')
    # Native persona is local to its account/service; opaque identity and owned
    # IDs are independent. Existing protocol adapters currently use persona 1.
    # Scaleform/Lua can round numeric IDs above 2**53; keep new ownership
    # comfortably below that limit while giving each UUID its own ID range.
    first = (int.from_bytes(owner.bytes[:4], 'big') << 20) + 1
    profile = _profile(creation_id, name, abbreviation, 7500)
    pending = pending_session(destination)
    if pending is not None:
        if pending['creation_id'] != creation_id:
            raise ValueError('Setup identity differs from creation request')
        profile = replace(profile, favorite_team_id=pending.get('favorite_team_id'),
                          favorite_country_id=pending.get('favorite_country_id'),
                          favorite_player_id=pending.get('favorite_player_id'))
    football = validate(starter_roster(creation_id, first), ContentCatalog())
    from .native_pack_sessions import PRIVATE_VERSION
    packs = {
        'persona_id': 1, 'next_catalog_id': 30001,
        'entitlements': [], 'consumed': [], 'identity_version': PRIVATE_VERSION,
    }
    gift = welcome_policy()['grant']
    rewards = []
    for ordinal in range(gift['packs']['count']):
        source = uuid.uuid5(creation, 'welcome-pack:%d' % ordinal)
        grant = {
            'reward_id': str(uuid.uuid5(source, 'setup-pack')),
            'source_id': str(source), 'source_kind': 'setup', 'account_id': str(owner),
            'persona_id': 1, 'cycle_id': str(creation), 'policy_version': VERSION,
            'certification': 'backend_only',
        }
        packs, granted = PackStore.source_grant_image(packs, gift['packs']['definition'], grant)
        rewards.append(granted['reward_id'])
    definition = replace(load_definition(ROOT / 'server/data/local-offline-definition.json'),
                         division_index=10).validate()
    images = {
        'profile.json': asdict(profile), 'football.json': FootballStore.encoded(football),
        'content.json': {'references': []}, 'packs.json': packs,
        'purchases.json': {'persona_id': 1, 'receipts': []},
        'products.json': {'persona_id': 1, 'products': []},
        'seasons.json': {'persona_id': 1, 'current': None},
        'definition.json': asdict(definition),
        'definition-response.json': definition_response(definition),
        'no-current-response.json': {'seasonId': -1},
        'control.json': json.loads((ROOT / 'server/data/roster-control.json').read_bytes()),
        'manifest.json': {'version': VERSION, 'creation_id': creation_id,
                          'note': 'Fresh supplied resource references; no copied ownership/history'},
        'first-run.json': {'version': VERSION, 'account': str(destination)},
        'welcome-gift.json': {'version': SELECTOR_VERSION, 'account': str(destination),
                              'generation': 1, 'served': {}},
    }
    from .first_run_catalog import initial_control, initial_store
    images.update(initial_store(destination))
    images['control.json'] = initial_control()
    images = {key: encode(value) for key, value in images.items()}
    record = {
        'version': VERSION, 'status': 'complete', 'creation_id': creation_id,
        'account_id': str(owner), 'persona_id': 1, 'identity_pid': profile.identity_pid,
        'user_id': profile.user_id, 'club_name': name, 'club_abbreviation': abbreviation,
        'credits_granted': gift['coins'], 'pack_grants': rewards,
        'policy_sha256': digest(POLICY.read_bytes()),
        'files': {key: digest(raw) for key, raw in images.items()},
    }
    return images, record


def _sync(directory):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def create_account(destination, name, abbreviation, *, creation_id, fault=None):
    """Explicit domain operation only; unproven client requests stay held.

    The caller supplies a stable UUID. Repeating it returns the original receipt
    even after play; a different operation or an existing legacy account refuses.
    """
    validate_identity(name, abbreviation)
    creation_id = str(uuid.UUID(creation_id))
    destination = Path(destination).absolute()
    if destination.is_symlink() or destination.resolve() != destination:
        raise ValueError('Account destination alias refused')
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.with_name('.' + destination.name + '.creating')
    lock_path = destination.with_name('.' + destination.name + '.creation.lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if destination.exists():
            if not (destination / RECEIPT).is_file():
                raise FileExistsError('Existing account will never be reseeded')
            value = inspect(destination)
            if (value['creation_id'], value['club_name'], value['club_abbreviation']) != (
                    creation_id, name, abbreviation):
                raise FileExistsError('Existing creation has different inputs')
            _sync(destination.parent)
            return value
        if stage.is_symlink():
            raise ValueError('Creation staging alias refused')
        stage.mkdir(mode=0o700, exist_ok=True)
        intent_path = stage / '.creation-intent'
        if (stage / RECEIPT).exists():
            record = receipt(stage)
        elif intent_path.exists():
            intent = json.loads(intent_path.read_bytes())
            record = intent['receipt']
            _validate_receipt(encode(record))
            if set(intent['images']) != set(record['files']):
                raise ValueError('Incomplete creation intent; staging preserved')
        else:
            if any(stage.iterdir()):
                raise ValueError('Unknown creation staging preserved')
            images, record = _images(name, abbreviation, creation_id, destination)
            intent = {'receipt': record, 'images': {key: raw.hex() for key, raw in images.items()}}
            atomic(intent_path, encode(intent))
            if fault:
                fault('prepared', 0)
        if (record['creation_id'], record['club_name'], record['club_abbreviation']) != (
                creation_id, name, abbreviation):
            raise ValueError('Creation recovery input conflict')
        if not (stage / RECEIPT).exists():
            # Check all existing images before changing any: unrelated edits
            # refuse instead of being silently overwritten during recovery.
            for key, encoded in intent['images'].items():
                if key not in record['files'] or Path(key).name != key:
                    raise ValueError('Invalid creation image path')
                raw = bytes.fromhex(encoded)
                if digest(raw) != record['files'][key]:
                    raise ValueError('Creation intent checksum conflict')
                path = stage / key
                if path.exists() and path.read_bytes() != raw:
                    raise ValueError('Creation image conflict; staging preserved')
            for index, (key, encoded) in enumerate(intent['images'].items()):
                atomic(stage / key, bytes.fromhex(encoded))
                if fault:
                    fault('after_image', index)
            atomic(stage / RECEIPT, encode(record))
        for key, checksum in record['files'].items():
            if digest((stage / key).read_bytes()) != checksum:
                raise ValueError('Completed creation image conflict')
        from .local_content import ContentCatalog
        from .local_football import FootballStore
        from .local_seasons import SeasonStore, load_definition
        FootballStore(stage / 'football.json', ContentCatalog(stage / 'content.json')).load(1)
        SeasonStore(stage / 'seasons.json', load_definition(stage / 'definition.json')).load()
        inspect(stage)
        if intent_path.exists():
            intent_path.unlink()
        _sync(stage)
        if fault:
            fault('before_publish', 0)
        os.rename(stage, destination)
        _sync(destination.parent)
        if fault:
            fault('after_publish', 0)
        return inspect(destination)
