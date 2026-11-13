"""Versioned earned-only caption bank; preserve every issued legacy alias.

Local presentation IDs, never EA product/resource identities. No recycling.
The existing source grant receipts determine stable per-definition ordinals.
"""
import copy
import hashlib
import json
from pathlib import Path

VERSION = 'reward_caption_capacity_v2'
FIRST = 10000
SLOTS = 512


def starts():
    from .reward_store_parity import policy
    from .revival_rewards import LABELS
    bindings=policy()['bindings']
    return {bindings[label]['definition']:FIRST+i*SLOTS for i,label in enumerate(LABELS)}


def upgrade(account, archive, certificate=None):
    from . import reward_release as release
    account,archive=Path(account).resolve(),Path(archive).resolve()
    old=json.loads((archive/release.MARKER).read_bytes())
    if old['version']!=release.VERSION:raise ValueError('Capacity upgrade requires preserved v1 release')
    value=copy.deepcopy(old)
    value.update(version=release.VERSION_V2,account=str(account),
        phase='enabled' if certificate else 'candidate',
        certificate=str(Path(certificate).resolve()) if certificate else None,
        certificate_sha256=release.sha(certificate) if certificate else None)
    value['capacity_extension']={'version':VERSION,'archive':str(archive),
        'manifest_sha256':release.sha(archive/'.lab-snapshot.json'),
        'legacy_marker_sha256':release.sha(archive/release.MARKER),
        'cutover_catalog_id':json.loads((archive/'packs.json').read_bytes())['next_catalog_id'],
        'first_wire_id':FIRST,'slots_per_definition':SLOTS}
    return value


def validate(account, value):
    from . import reward_release as release
    p=value['capacity_extension'];account=Path(account).resolve()
    if (type(p) is not dict or set(p)!={'version','archive','manifest_sha256','legacy_marker_sha256',
            'cutover_catalog_id','first_wire_id','slots_per_definition'} or p['version']!=VERSION
            or type(p['first_wire_id']) is not int or p['first_wire_id']!=FIRST
            or type(p['slots_per_definition']) is not int or p['slots_per_definition']!=SLOTS):
        raise ValueError('Invalid reward capacity extension')
    archive=Path(p['archive']).resolve()
    if release.ROOT/'reports' not in archive.parents or archive==account or account in archive.parents:
        raise ValueError('Separate capacity cutover archive required')
    manifest=archive/'.lab-snapshot.json'
    if release.sha(manifest)!=p['manifest_sha256']:raise ValueError('Capacity cutover manifest changed')
    files=json.loads(manifest.read_bytes())['sha256']
    if not {'packs.json','purchases.json','profile.json',release.MARKER}<=files.keys():
        raise ValueError('Incomplete capacity cutover archive')
    for name,digest in files.items():
        path=archive/name
        if Path(name).name!=name or path.is_symlink() or path.stat().st_nlink!=1 or release.sha(path)!=digest:
            raise ValueError('Capacity cutover archive changed')
    if release.sha(archive/release.MARKER)!=p['legacy_marker_sha256']:
        raise ValueError('Legacy reward marker changed')
    old=json.loads((archive/release.MARKER).read_bytes())
    if (old['version']!=release.VERSION or old['phase'] not in ('candidate','enabled') or
            any(old[k]!=value[k] for k in ('origin_archive','origin_manifest_sha256','contracts','policies'))):
        raise ValueError('Capacity upgrade cannot replace legacy reward contracts')
    if value['phase']=='enabled':
        if old['phase']!='enabled' or release.sha(old['certificate'])!=old['certificate_sha256']:
            raise ValueError('Enabled capacity requires certified legacy release')
        proof=json.loads(Path(old['certificate']).read_bytes())
        if proof.get('status')!='STOCK_VERIFIED_REWARD_STORE_RELEASE':
            raise ValueError('Legacy release certificate incomplete')
    baseline=json.loads((archive/'packs.json').read_bytes())
    if (baseline.get('prepared') or type(p['cutover_catalog_id']) is not int
            or p['cutover_catalog_id']!=baseline['next_catalog_id'] or not 30001<=p['cutover_catalog_id']<=65535):
        raise ValueError('Quiescent prospective capacity cutover required')
    old_profile=json.loads((archive/'profile.json').read_bytes())
    current=json.loads((account/'profile.json').read_bytes())
    if any(old_profile[k]!=current[k] for k in ('persona_id','identity_pid','user_id')):
        raise ValueError('Capacity owner changed')
    return {'cutover':p['cutover_catalog_id'],'sources':baseline.get('source_grants',[])}


def aliases(store, value, policy, journal=None):
    from .native_source_pack_presentation import _aliases
    baseline=policy['capacity'];sources=value.get('source_grants',[])
    old=baseline['sources']
    if sources[:len(old)]!=old:raise ValueError('Pre-cutover source history changed')
    legacy={**value,'source_grants':sources[:len(old)]}
    mapping=_aliases(store,legacy,policy,journal)
    namespace=starts();counts={definition:0 for definition in namespace}
    owned={e['catalog_id']:e for e in value['entitlements']+value['consumed']}
    last=baseline['cutover']-1
    for source in sources[len(old):]:
        e=source['entitlement'];key=e['catalog_id'];definition=e['definition']
        if (definition not in counts or key<=last or source['source_kind'] not in ('fixture','season')
                or source['policy_version']!='reward_store_parity_v1' or e.get('untradeable') is not True
                or key not in owned or any(owned[key].get(k)!=v for k,v in e.items())):
            raise ValueError('Conflicting prospective capacity source')
        ordinal=counts[definition]
        if ordinal>=SLOTS:raise ValueError('Earned caption capacity exhausted for definition')
        mapping[key]=namespace[definition]+ordinal
        counts[definition]+=1;last=key
    # All internal IDs>=30001 and paid products>=40001. Keep this independent
    # check explicit instead of trusting later validators to repair a collision.
    reserved={i for first in namespace.values() for i in range(first,first+SLOTS)}
    if reserved&set(owned) or len(set(mapping.values()))!=len(mapping):
        raise ValueError('Capacity ownership/alias collision')
    if journal is None and store.path.with_name('purchases.json').exists():
        journal=json.loads(store.path.with_name('purchases.json').read_bytes())
    if any({r[k] for k in ('product_id','sku_id','next_product_id') if k in r}&reserved
           for r in (journal or {}).get('receipts',[])):
        raise ValueError('Historical paid offer collides with capacity bank')
    return mapping


def validate_capacity(store, value, policy, count, required=None):
    aliases(store,value,policy)
    definitions=starts();used={d:0 for d in definitions}
    for source in value.get('source_grants',[])[len(policy['capacity']['sources']):]:
        used[source['entitlement']['definition']]+=1
    needed=required if required is not None else {d:count for d in definitions}
    if any(d not in used or type(n) is not int or n<0 or used[d]+n>SLOTS for d,n in needed.items()):
        raise ValueError('Reserved earned caption capacity exhausted before match')


def allows_low_open(account):
    from . import reward_release as release
    from . import native_pack_sessions as sessions
    return sessions.selected(account) or (release.selected(account) and 'capacity' in release.POLICY)
