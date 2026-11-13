"""Explicit archived admission of atomic rewards beside the certified Store.

Reuses the existing source caption allocator and account transaction journal.
No historical receipt, paid offer, ownership or reward amount is migrated.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT/'server/data/development/fm16in2026'
MARKER = 'reward-release.json'
VERSION = 'local_reward_release_v1'
VERSION_V2 = 'local_reward_release_v2'
ACCOUNT = POLICY = None
CONTRACTS = [ROOT/'reports/reward-pack-parity/2026-10-26/frozen/certificate.json',
             ROOT/'reports/early-season-payout/2026-10-26/frozen/certificate.json']
POLICIES = [ROOT/'server/policy/reward-store-parity-v1.json',
            ROOT/'server/policy/early-season-completion-v1.json']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def marker(account, archive, certificate=None):
    account, archive = Path(account).resolve(), Path(archive).resolve()
    certificate = Path(certificate).resolve() if certificate else None
    return {'version': VERSION, 'account': str(account),
            'phase': 'enabled' if certificate else 'candidate',
            'origin_archive': str(archive), 'origin_manifest_sha256': sha(archive/'.lab-snapshot.json'),
            'contracts': {str(p): sha(p) for p in CONTRACTS},
            'policies': {str(p): sha(p) for p in POLICIES},
            'certificate': str(certificate) if certificate else None,
            'certificate_sha256': sha(certificate) if certificate else None}


def validate(account):
    if Path(account).is_symlink():
        raise ValueError('Reward account alias refused')
    account = Path(account).resolve()
    if account != REAL and (ROOT/'reports' not in account.parents or account.name != 'isolated-account'):
        raise ValueError('Reward release account differs')
    value = json.loads((account/MARKER).read_bytes())
    keys = {'version','account','phase','origin_archive','origin_manifest_sha256','contracts',
            'policies','certificate','certificate_sha256'}
    if value.get('version')==VERSION_V2:keys.add('capacity_extension')
    if set(value) != keys or value['version'] not in (VERSION,VERSION_V2) or value['account'] != str(account):
        raise ValueError('Invalid reward release marker')
    for path in account.glob('*.json'):
        if path.is_symlink() or path.stat().st_nlink != 1:
            raise ValueError('Reward account file alias refused')
    archive = Path(value['origin_archive']).resolve()
    if ROOT/'reports' not in archive.parents or archive == account or account in archive.parents:
        raise ValueError('Separate reward deployment archive required')
    if sha(archive/'.lab-snapshot.json') != value['origin_manifest_sha256']:
        raise ValueError('Reward archive manifest changed')
    files = json.loads((archive/'.lab-snapshot.json').read_bytes())['sha256']
    if not {'profile.json','packs.json','purchases.json','products.json','football.json',
            'seasons.json','gameplay-release.json','store-release.json'} <= files.keys():
        raise ValueError('Incomplete reward archive')
    for name, digest in files.items():
        path = archive/name
        if Path(name).name != name or path.is_symlink() or sha(path) != digest:
            raise ValueError('Reward archive changed')
    old, current = [json.loads((p/'profile.json').read_bytes()) for p in (archive, account)]
    if any(old[k] != current[k] for k in ('persona_id','identity_pid','user_id')):
        raise ValueError('Reward account identity changed')
    from .store_release import configuration_preserved
    if not configuration_preserved(account, archive):
        raise ValueError('Reward admission changed Store configuration')
    if value['contracts'] != {str(p): sha(p) for p in CONTRACTS} or value['policies'] != {str(p): sha(p) for p in POLICIES}:
        raise ValueError('Reward contract/policy changed')
    if value['phase'] == 'candidate':
        if account == REAL or value['certificate'] is not None or value['certificate_sha256'] is not None:
            raise ValueError('Uncertified normal reward activation refused')
    elif value['phase'] == 'enabled':
        cert = Path(value['certificate'])
        if cert.is_symlink() or ROOT/'reports' not in cert.resolve().parents or sha(cert) != value['certificate_sha256']:
            raise ValueError('Reward composition certificate changed')
        proof = json.loads(cert.read_bytes())
        required=(('store_preserved','source_pack_verified','early_season_verified','restart_verified','exact_retry_verified')
                  if value['version']==VERSION else ('old_aliases_preserved','extended_namespace_verified',
                    'compact_records_verified','restart_verified','exact_retry_verified'))
        status='STOCK_VERIFIED_REWARD_STORE_RELEASE' if value['version']==VERSION else 'STOCK_VERIFIED_REWARD_CAPACITY_V2'
        if (proof.get('status') != status or
                not all(proof.get(k) is True for k in required) or
                type(proof.get('native_capture')) is not int or proof['native_capture'] <= 0):
            raise ValueError('Reward composition certificate incomplete')
    else:
        raise ValueError('Invalid reward deployment phase')
    if value['version']==VERSION_V2:
        from .reward_capacity import validate as validate_extension
        validate_extension(account,value)
    return value


def configure(account=None):
    global ACCOUNT, POLICY
    ACCOUNT = POLICY = None
    if account is None:
        return
    account = Path(account).resolve()
    from . import gameplay_release
    if not gameplay_release.selected(account):
        raise ValueError('Reward admission requires existing gameplay release')
    value = validate(account)
    from .native_source_pack_presentation import VERSION_V4,_aliases
    before = json.loads((Path(value['origin_archive'])/'packs.json').read_bytes())
    policy = {'version': VERSION_V4, 'first_catalog_id': before['next_catalog_id'],
              'old_sources': before.get('source_grants', []), 'marker_sha256': sha(account/MARKER)}
    if value['version']==VERSION_V2:
        from .reward_capacity import validate as validate_extension
        policy.update(capacity=validate_extension(account,value),compact_records=True)
    from .local_packs import PackStore
    store=PackStore(account/'packs.json')
    from .native_pack_sessions import legacy_state
    if 'capacity' in policy:
        from .reward_capacity import aliases as extended_aliases
        extended_aliases(store,legacy_state(store.load(),'packs'),policy)
    else:_aliases(store,store.load(),policy)
    ACCOUNT, POLICY = account,policy


def selected(account):
    if ACCOUNT is None or Path(account).resolve() != ACCOUNT:
        return False
    if sha(ACCOUNT/MARKER) != POLICY['marker_sha256']:
        raise ValueError('Reward release selector changed during runtime')
    return True


def aliases(store, value=None, journal=None):
    if not selected(store.path.parent):
        return {}
    from .native_pack_sessions import legacy_state
    current=legacy_state(store.load() if value is None else value,'packs')
    if journal is not None:journal=legacy_state(journal,'purchases')
    if 'capacity' in POLICY:
        from .reward_capacity import aliases as extended_aliases
        return extended_aliases(store,current,POLICY,journal)
    from .native_source_pack_presentation import _aliases
    return _aliases(store, store.load() if value is None else value, POLICY, journal)


def descriptions(store,*,value=None):
    if not selected(store.path.parent):
        return []
    aliases(store,value)
    from .native_source_pack_presentation import starts, SLOTS
    rows=[(wire, definition) for definition, first in starts(POLICY).items()
          for wire in range(first, first+SLOTS)]
    if 'capacity' in POLICY:
        from .reward_capacity import starts as extra_starts,SLOTS as extra_slots
        rows.extend((wire,definition) for definition,first in extra_starts().items()
                    for wire in range(first,first+extra_slots))
    return rows


def validate_capacity(store, count, required=None):
    from .fresh_account_runtime import selected as fresh_selected
    if fresh_selected(store.path.parent):
        from .native_pack_sessions import validate_capacity as session_capacity
        return session_capacity(store, count, required)
    if not selected(store.path.parent):
        return
    from .native_source_pack_presentation import SLOTS
    if type(count) is not int or count < 0:
        raise ValueError('Invalid reward capacity request')
    value = store.load()
    from . import native_pack_sessions as sessions
    if sessions.selected(store.path.parent):return sessions.validate_capacity(store,count,required)
    if 'capacity' in POLICY:
        from .reward_capacity import validate_capacity as extra_capacity
        return extra_capacity(store,value,POLICY,count,required)
    aliases(store, value)
    if value['next_catalog_id']+count > POLICY['first_catalog_id']+SLOTS:
        raise ValueError('Reserved reward caption capacity exhausted before match')


def compact_records(account):
    from .fresh_account_runtime import selected as fresh_selected
    if fresh_selected(account):
        return True
    return selected(account) and POLICY.get('compact_records') is True
