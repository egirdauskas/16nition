"""Original consumable mappings and explicit, certificate-backed effect admission.

01026a50 supplies formation modifiers and packed from/to position bytes.
Ownership, rendering and an admitted effect are separate contracts.
"""
import hashlib
import json
from pathlib import Path
from .local_consumables import INJURY_SUBTYPES

ROOT = Path(__file__).resolve().parents[1]
MARKER = 'consumable-effects-release.json'
FEATURES = frozenset(('inventory_search', 'player_formation', 'manager_formation',
                      'training', 'position', 'healing'))
ACCOUNT = POLICY = None

# Original enrichment01026a50, cases71..86 and121..136, including shared labels.
FORMATION_IDS = (1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31)
PLAYER_FORMATIONS = dict(zip(range(71, 87), FORMATION_IDS))
MANAGER_FORMATIONS = dict(zip(range(121, 137), FORMATION_IDS))
# Original nested+80 uint16: low byte is source, high byte destination.
POSITION_PAIRS = dict(zip(range(91, 111), (
    (8, 7), (7, 8), (2, 3), (3, 2), (16, 27), (12, 23), (27, 16),
    (23, 12), (27, 22), (23, 20), (22, 27), (20, 23), (14, 18),
    (18, 14), (10, 14), (14, 10), (18, 21), (21, 18), (21, 25), (25, 21))))
TRAINING_SUBTYPES = frozenset(range(51, 58)) | frozenset(range(61, 68))
MAPPED_SUBTYPES = (frozenset(PLAYER_FORMATIONS) | frozenset(MANAGER_FORMATIONS)
                   | frozenset(POSITION_PAIRS) | TRAINING_SUBTYPES | INJURY_SUBTYPES)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def configure(account=None):
    global ACCOUNT, POLICY
    ACCOUNT = POLICY = None
    if account is None:
        return
    account = Path(account).resolve()
    from .fresh_account_runtime import selected as fresh_selected
    if fresh_selected(account):
        ACCOUNT, POLICY = account, {'fresh_account': True, 'features': sorted(FEATURES)}
        return
    marker = account / MARKER
    if not marker.exists():
        return
    value = json.loads(marker.read_bytes())
    if (marker.is_symlink() or set(value) != {
            'version', 'account', 'archive', 'manifest_sha256', 'phase',
            'features', 'certificate', 'certificate_sha256'} or
            value['version'] != 'consumable_effects_v1' or
            value['account'] != str(account) or
            type(value['features']) is not list or
            len(set(value['features'])) != len(value['features']) or
            not set(value['features']) <= FEATURES):
        raise ValueError('Invalid consumable effect admission')
    archive = Path(value['archive']).resolve()
    if (ROOT / 'reports' not in archive.parents or archive == account or
            sha(archive / '.lab-snapshot.json') != value['manifest_sha256']):
        raise ValueError('Separate consumable archive required')
    files = json.loads((archive / '.lab-snapshot.json').read_bytes())['sha256']
    if not {'football.json', 'profile.json'} <= files.keys():
        raise ValueError('Incomplete consumable archive')
    for name, digest in files.items():
        p = archive / name
        if Path(name).name != name or p.is_symlink() or sha(p) != digest:
            raise ValueError('Consumable archive changed')
    old = json.loads((archive / 'profile.json').read_bytes())
    current = json.loads((account / 'profile.json').read_bytes())
    if any(old[k] != current[k] for k in ('persona_id', 'identity_pid', 'user_id')):
        raise ValueError('Consumable owner changed')
    if value['phase'] == 'candidate':
        if (ROOT / 'reports' not in account.parents or account.name != 'isolated-account'
                or not (account / '.lab-snapshot.json').is_file()
                or value['certificate'] is not None or value['certificate_sha256'] is not None):
            raise ValueError('Unverified consumable effects are isolated-only')
    elif value['phase'] == 'enabled':
        from .store_release import REAL
        certificate = Path(value['certificate']).resolve()
        if (account != REAL or not any(p in certificate.parents for p in
                (ROOT / 'reports/consumable-application', ROOT / 'reports/position-healing'))
                or certificate.is_symlink() or sha(certificate) != value['certificate_sha256']):
            raise ValueError('Consumable effect certificate changed')
        proof = json.loads(certificate.read_bytes())
        if (proof.get('status') != 'STOCK_VERIFIED_CONSUMABLE_APPLICATION'
                or proof.get('features') != value['features']
                or any(proof.get(k) is not True for k in
                       ('source_retirement', 'native_effect', 'restart_verified',
                        'retry_verified', 'ownership_preserved'))):
            raise ValueError('Incomplete consumable effect certificate')
        if 'training' in value['features'] and proof.get('one_game_expiry') is not True:
            raise ValueError('Training application requires verified one-game expiry')
        if 'position' in value['features'] and proof.get('position_roundtrip') is not True:
            raise ValueError('Position application requires verified roundtrip')
        if 'healing' in value['features'] and any(proof.get(k) is not True for k in
                ('native_injury_persistence', 'healing_application')):
            raise ValueError('Healing requires verified injury and application')
    else:
        raise ValueError('Invalid consumable effect phase')
    ACCOUNT, POLICY = account, dict(value, marker_sha256=sha(marker))


def features(store):
    if ACCOUNT is None or store.path.resolve().parent != ACCOUNT:
        return frozenset()
    if POLICY.get('fresh_account'):
        from .fresh_account_runtime import selected as fresh_selected
        return FEATURES if fresh_selected(ACCOUNT) else frozenset()
    if sha(ACCOUNT / MARKER) != POLICY['marker_sha256']:
        raise ValueError('Consumable effect selector changed during runtime')
    return frozenset(POLICY['features'])


def effective_position(player):
    if player.preferred_position is not None:
        return player.preferred_position
    if player.special_version_id:
        from .reconstructed_specials import version
        return version(player.special_version_id).position
    from .local_content_source import position_for
    return position_for(player.resource_id)


def guard_training_application(store, source_id):
    """Preparation may change training; an already playing source may not."""
    selected=features(store)
    if not selected & {'training','healing'}:
        return
    source = next((i for i in store.load(1).owned_consumables if i.instance_id == source_id), None)
    if source is None:
        return  # Completed application retries are read-only.
    from .local_consumables import inventory_reference
    subtype=inventory_reference(source.resource_id)['cardsubtype']
    from .local_consumables import INJURY_SUBTYPES
    healing='healing' in selected and subtype in INJURY_SUBTYPES
    if not healing and subtype not in TRAINING_SUBTYPES:
        return
    journal = store.path.with_name('native-seasons.json')
    active = json.loads(journal.read_bytes()).get('active_match') if journal.exists() else None
    if active and active.get('status') == 'playing':
        raise ValueError(('Healing' if healing else 'Training')+' cannot change during an accepted playing match')
