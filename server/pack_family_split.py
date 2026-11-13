"""Authorized prospective pack-family separation; old draws remain immutable."""
import copy
import hashlib
import json
from pathlib import Path
from .policy_memo import policy_memo

PATH=Path(__file__).parent/'policy/pack-family-split-v1.json'
DEFINITIONS=('revival_consumables_only_v4','revival_customization_v1')
KEY='pack_family_split'


def policy():
    p=json.loads(PATH.read_bytes())
    if (p['version']!='pack_family_split_v1' or p['classification']!='revival_policy'
            or p['default_enabled'] is not False or p['item_count']!=12
            or p['tier_counts']!={'bronze':4,'silver':4,'gold':4} or p['rare_count']!=3
            or tuple(x['definition'] for x in p['products'])!=DEFINITIONS
            or p['fifa_points_enabled'] is not False or p['featured_only'] is not True):
        raise ValueError('Unapproved pack-family split')
    expected=[('revival_consumables_only_v4','Consumables Pack','consumable',62300,62302),
              ('revival_customization_v1','Customization Pack','club_item',62301,62334)]
    if any(row!={'definition':d,'name':name,'family':family,'product_id':sku,
                    'first_offer_id':first,'coin_price':5000}
           for row,(d,name,family,sku,first) in zip(p['products'],expected)):
        raise ValueError('Unapproved split product identity or price')
    return p


def definitions():
    p=policy();out={}
    for row in p['products']:
        rule={'provenance':'revival_policy','name':row['name'],'item_family':row['family'],
              'quality':'mixed','item_count':12,'minimum_rare':3,'exact_rare':True,
              'tier_counts':p['tier_counts'],'selection':'typed_tier_quota_v1',
              'weights':{'common':1,'rare':1}}
        if row['family']=='consumable':rule.update(consumable_scope='all',consumable_pool=p['consumable_pool'])
        elif row['family']=='club_item':rule['club_item_pool']=p['club_item_pool']
        else:raise ValueError('Unsupported split family')
        out[row['definition']]=rule
    return out


def validate_definition(key,rule):
    expected=definitions().get(key)
    if rule!=expected or any(type(rule[k]) is not type(v) for k,v in expected.items()):
        raise ValueError('Split pack guarantees changed')
    return rule


def pool(rule):
    from .local_packs import MixedPull
    from .local_club_items import references,quality
    if rule['item_family']=='club_item':
        return tuple(MixedPull(rid,None,row['rare'],quality(row),row['item_type']) for rid,row in references().items())
    from .local_consumables import pack_references
    return tuple(MixedPull(rid,None,int(row['weightrare']>0),quality(row),'consumable')
                 for rid,row in pack_references(rule['consumable_pool']).items())


def starts():
    return {r['definition']:r['first_offer_id'] for r in policy()['products']}


@policy_memo
def catalog():
    from .store_pool_amendment import catalog as previous
    p=policy();value=copy.deepcopy(previous());value['version']='local_store_catalog_v6'
    prior=next(i for i,row in enumerate(value['products']) if row['definition']==p['previous_consumables'])
    rows=[{'product_id':r['product_id'],'definition':r['definition'],'provenance':'revival_policy',
           'coin_price':r['coin_price'],'repeatable':True,'purchase_limit':1,'featured':True}
          for r in p['products']]
    value['products'][prior]=rows[0];value['products'].append(rows[1])
    return value


def captions(definition):
    if definition not in DEFINITIONS:return None
    row=next(r for r in policy()['products'] if r['definition']==definition)
    family='consumables' if row['family']=='consumable' else 'club items'
    return {'NAME':row['name'],'DESC':f'4 Gold, 4 Silver and 4 Bronze {family}. 3 Rares.',
            'SHORT':'12 ITEMS\n4 GOLD\n3 RARES'}


def documents(account,backup,certificate=None):
    """Archive-bound configuration only; no old product/pack receipts rewritten."""
    from . import store_release,native_paid_pack_presentation as paid
    from .native_paid_caption_reservations import VERSION_V8,VERSION_V9
    account,backup=Path(account).resolve(),Path(backup).resolve()
    release=json.loads((backup/store_release.MARKER).read_bytes())
    marker=json.loads((backup/paid.MARKER).read_bytes())
    from .store_pool_amendment import catalog as previous
    if (release['version']!='local_store_release_v5' or 'pool_amendment' not in release
            or KEY in release or marker['version']!=VERSION_V8
            or json.loads((backup/'products.json').read_bytes())!=previous()):
        raise ValueError('Archived certified current Store required')
    rows=catalog()
    marker.update(version=VERSION_V9,caption_origin_archive=str(backup))
    marker['caption_bindings'].update({str(row['product_id']):{
        'definition':row['definition'],'first_offer_id':row['first_offer_id']} for row in policy()['products']})
    def sha_value(value):return hashlib.sha256((json.dumps(value,indent=2)+'\n').encode()).hexdigest()
    certificate=Path(certificate).resolve() if certificate else None
    release.update(account=str(account),products_sha256=sha_value(rows),presentation_sha256=sha_value(marker))
    release[KEY]={'version':policy()['version'],'policy_sha256':hashlib.sha256(PATH.read_bytes()).hexdigest(),
        'archive':str(backup),'manifest_sha256':hashlib.sha256((backup/'.lab-snapshot.json').read_bytes()).hexdigest(),
        'certificate':str(certificate) if certificate else None,
        'certificate_sha256':hashlib.sha256(certificate.read_bytes()).hexdigest() if certificate else None}
    return {'products.json':rows,paid.MARKER:marker,store_release.MARKER:release}


def validate_deployment(account,release):
    from . import store_release,native_paid_pack_presentation as paid
    from .store_pool_amendment import documents as old_documents
    account=Path(account).resolve();extension=release[KEY]
    fields={'version','policy_sha256','archive','manifest_sha256','certificate','certificate_sha256'}
    if (set(extension)!=fields or extension['version']!=policy()['version']
            or extension['policy_sha256']!=hashlib.sha256(PATH.read_bytes()).hexdigest()):
        raise ValueError('Pack split policy changed')
    backup=Path(extension['archive']).resolve()
    root=Path(__file__).resolve().parents[1]
    if root/'reports/store-pack-split' not in backup.parents or backup==account:
        raise ValueError('Separate preserved pack split archive required')
    if hashlib.sha256((backup/'.lab-snapshot.json').read_bytes()).hexdigest()!=extension['manifest_sha256']:
        raise ValueError('Pack split archive manifest changed')
    for name,digest in json.loads((backup/'.lab-snapshot.json').read_bytes())['sha256'].items():
        path=backup/name
        if Path(name).name!=name or path.is_symlink() or path.stat().st_nlink!=1 or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('Pack split archive changed')
    old=json.loads((backup/store_release.MARKER).read_bytes())
    # Full parent certificate/archive checks also run in Store.validate. Check
    # its exact admitted amended configuration without rebinding old identities.
    old_expected=old_documents(store_release.REAL,old['pool_amendment']['archive'])
    if any(json.loads((backup/name).read_bytes())!=value for name,value in old_expected.items()):
        raise ValueError('Pack split parent configuration differs')
    certificate=Path(extension['certificate']).resolve() if extension['certificate'] else None
    if certificate is None or root/'reports/store-pack-split' not in certificate.parents or certificate.is_symlink():
        raise ValueError('Certified pack split required for release')
    if hashlib.sha256(certificate.read_bytes()).hexdigest()!=extension['certificate_sha256']:
        raise ValueError('Pack split certificate changed')
    proof=json.loads(certificate.read_bytes())
    if (proof.get('status')!='STOCK_VERIFIED_PACK_FAMILY_SPLIT' or
            any(proof.get(k) is not True for k in ('consumables_only','club_items_only','native_store_verified',
                'restart_verified','exact_retry_verified')) or
            any(type(proof.get(k)) is not int or proof[k]<=0 for k in ('purchase_capture','open_capture','restart_capture'))):
        raise ValueError('Pack split certificate incomplete')
    from . import gameplay_release
    owner=store_release.REAL if account!=store_release.REAL and gameplay_release.selected(account) else account
    expected=documents(owner,backup,certificate)
    if release!=expected[store_release.MARKER] or json.loads((account/paid.MARKER).read_bytes())!=expected[paid.MARKER]:
        raise ValueError('Pack split configuration differs')
    for name,key in (('purchases.json','receipts'),('packs.json','consumed')):
        prior=json.loads((backup/name).read_bytes())[key];current=json.loads((account/name).read_bytes())[key]
        if current[:len(prior)]!=prior:raise ValueError('Pre-split history changed')
    return expected['products.json']
