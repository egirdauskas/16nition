"""Recovered StoreStyle artwork enum, explicit-account opt-in catalog projection only.

Effective supplied libfefowzinc StoreStyle:BRONZE1/SILVER2/GOLD3. Original
PackComponent/MyPackComponent compare packtype against those constants; shared
021e8768 exports native assetId, populated from RS4key13 source+48. Source
provenance and complete ABC methods:reports/overnight/2026-10-13-visible-store/pack-art.
"""
from pathlib import Path
from .pack_policy import CLASSIC_MIXED_BINDINGS
from .local_packs import DEFINITIONS
ACCOUNT=None
ART={'bronze':1,'silver':2,'gold':3}

def configure(account=None):
 global ACCOUNT
 if account is None:ACCOUNT=None;return
 account=Path(account)
 from .store_release import projection_account
 validated=projection_account([account/name for name in ('profile.json','football.json','content.json','packs.json','seasons.json','definition.json','control.json')])
 ACCOUNT=validated

def project(value,store,*,pack_state=None):
 if ACCOUNT is None:return value
 if store.path.resolve().parent!=ACCOUNT:raise ValueError('Artwork projection account selector differs')
 from .local_store import active_offers
 pack_state=store.load() if pack_state is None else pack_state
 refs={e['catalog_id']:e['definition'] for e in pack_state['entitlements']}
 if store.path.with_name('products.json').exists():
  for row in active_offers(store.path.with_name('products.json')):
   key=row['product_id'];definition=row['definition']
   if key in refs and refs[key]!=definition:raise ValueError('Conflicting paid/unopened artwork identity')
   refs[key]=definition
 rows=[];club_definitions=None
 for row in value['purchase']:
  row=dict(row);definition=refs.get(row['id'])
  if definition and (
      DEFINITIONS[definition].get('selection') == 'reviewed_tier_special_v1'
      or definition == 'revival_carnival_david_luiz_reward_v1'
  ):
   row['assetId'] = ART[DEFINITIONS[definition]['quality']]
  if definition and DEFINITIONS[definition].get('selection')=='consumables_tier_quota_v1':row['assetId']=ART['gold']
  if definition and DEFINITIONS[definition].get('selection') == 'specific_supplied_consumable_v1':
   row['assetId'] = ART[DEFINITIONS[definition]['quality']]
  if definition and DEFINITIONS[definition].get('selection')=='typed_tier_quota_v1':
   row['assetId']=ART['gold' if DEFINITIONS[definition]['quality']=='mixed' else DEFINITIONS[definition]['quality']]
  from .classic_pack_store import SUPPORTED_V8,SUPPORTED_V9,SUPPORTED_V10,SUPPORTED_V11
  if definition and DEFINITIONS[definition].get('club_item_pool'):
   if club_definitions is None:
    from .club_item_packs import bindings
    club_definitions=set(bindings().values())
   if definition in club_definitions:row['assetId']=ART[DEFINITIONS[definition]['quality']]
  if definition in SUPPORTED_V8.values() or definition in SUPPORTED_V9.values() or definition in SUPPORTED_V10.values() or definition in SUPPORTED_V11.values():row['assetId']=ART[DEFINITIONS[definition]['quality']]
  # STORE-006: release-demo packs use the standard tier artwork.
  from .store_demo_offers import policy as demo_policy
  if definition and definition in {o['definition'] for o in demo_policy()['offers']}:row['assetId']=ART[DEFINITIONS[definition]['quality']]
  if definition in CLASSIC_MIXED_BINDINGS.values() or definition in ('revival_rare_players_v1','revival_premium_gold_players_v3','revival_jumbo_premium_gold_mixed_v1','revival_jumbo_rare_players_v1','revival_ultimate_players_v1'):row['assetId']=ART[DEFINITIONS[definition]['quality']]
  rows.append(row)
 from .store_single_artwork import project as single_artwork
 return single_artwork({**value,'purchase':rows},store,refs)
