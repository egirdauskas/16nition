"""Backend-only Store projection; prices come solely from the approved table.

Does not register a live overlay, copy products into a real account, or activate
native UI. These IDs are local test identities, not recovered EA product IDs.
"""
import json
from pathlib import Path
from .revival_rewards import load_reward_policy
from .local_packs import DEFINITIONS
from .pack_policy import CLASSIC_MIXED_BINDINGS,all_tier_special_bindings,expanded_consumable_bindings,filtered_consumable_bindings,crowd_filtered_consumable_bindings
POLICY=Path(__file__).parent/'policy/classic-pack-store-backend.json'
POLICY_V2=Path(__file__).parent/'policy/classic-pack-store-backend-v2.json'
POLICY_V3=Path(__file__).parent/'policy/classic-pack-store-backend-v3.json'
POLICY_V4=Path(__file__).parent/'policy/classic-pack-store-backend-v4.json'
POLICY_V5=Path(__file__).parent/'policy/classic-pack-store-backend-v5.json'
POLICY_V6=Path(__file__).parent/'policy/classic-pack-store-backend-v6.json'
POLICY_V7=Path(__file__).parent/'policy/classic-pack-store-backend-v7.json'
POLICY_V8=Path(__file__).parent/'policy/classic-pack-store-backend-v8.json'
POLICY_V9=Path(__file__).parent/'policy/classic-pack-store-backend-v9.json'
POLICY_V10=Path(__file__).parent/'policy/classic-pack-store-backend-v10.json'
POLICY_V11=Path(__file__).parent/'policy/classic-pack-store-backend-v11.json'
SUPPORTED=CLASSIC_MIXED_BINDINGS
SUPPORTED_V3={**SUPPORTED,'Rare Players':'revival_rare_players_v1'}
SUPPORTED_V4={**SUPPORTED_V3,'Premium Gold Players':'revival_premium_gold_players_v3'}
SUPPORTED_V5={**SUPPORTED_V4,'Jumbo Premium Gold':'revival_jumbo_premium_gold_mixed_v1','Mega':'revival_mega_mixed_v1'}
SUPPORTED_V6={**SUPPORTED_V5,'Jumbo Rare Players':'revival_jumbo_rare_players_v1'}
SUPPORTED_V7={**SUPPORTED_V6,'Ultimate':'revival_ultimate_players_v1'}
SUPPORTED_V8=all_tier_special_bindings()
SUPPORTED_V9=expanded_consumable_bindings()
SUPPORTED_V10=filtered_consumable_bindings()
SUPPORTED_V11=crowd_filtered_consumable_bindings()
LATEST_POLICY=POLICY_V11
LATEST_SUPPORTED=SUPPORTED_V11
VERSIONS={
 'classic_pack_store_backend_v1':tuple(SUPPORTED)[:4],
 'classic_pack_store_backend_v2':tuple(SUPPORTED),
 'classic_pack_store_backend_v3':tuple(SUPPORTED_V3),
 'classic_pack_store_backend_v4':tuple(SUPPORTED_V4),
 'classic_pack_store_backend_v5':tuple(SUPPORTED_V5),
 'classic_pack_store_backend_v6':tuple(SUPPORTED_V6),
 'classic_pack_store_backend_v7':tuple(SUPPORTED_V7),
 'classic_pack_store_backend_v8':tuple(SUPPORTED_V8),
 'classic_pack_store_backend_v9':tuple(SUPPORTED_V9),
 'classic_pack_store_backend_v10':tuple(SUPPORTED_V10),
 'classic_pack_store_backend_v11':tuple(SUPPORTED_V11),
}

def projection(path=POLICY,*,backend_only=False):
 if backend_only is not True:raise ValueError('Classic Store projection disabled by default')
 value=json.loads(Path(path).read_text())
 if type(value) is not dict or type(value.get('version')) is not str or value['version'] not in VERSIONS:
  raise ValueError('Unsupported classic Store policy version')
 labels=VERSIONS[value['version']]
 fixed={'version':value['version'],'classification':'revival_policy',
        'default_enabled':False,'stock_delivery_enabled':False,'price_source':'offline_rewards_v1',
        'identity_namespace':'server_local_test_sku_not_ea_product_id'}
 if set(value)!=set(fixed)|{'bindings'} or any(type(value[k]) is not type(v) or value[k]!=v for k,v in fixed.items()):
  raise ValueError('Invalid disabled classic Store policy')
 if type(value['bindings']) is not dict or set(value['bindings'])!=set(labels):raise ValueError('Versioned supported classic bindings required')
 supported=SUPPORTED_V11 if value['version']=='classic_pack_store_backend_v11' else SUPPORTED_V10 if value['version']=='classic_pack_store_backend_v10' else SUPPORTED_V9 if value['version']=='classic_pack_store_backend_v9' else SUPPORTED_V8 if value['version']=='classic_pack_store_backend_v8' else SUPPORTED_V7
 table=load_reward_policy()['permanent_coin_catalog'];rows=[];seen=set()
 for label,binding in value['bindings'].items():
  if (type(binding) is not dict or set(binding)!={'product_id','definition'} or
      binding['definition']!=supported[label] or type(binding['product_id']) is not int or
      not 40001<=binding['product_id']<=65535 or binding['product_id'] in seen):raise ValueError('Invalid local SKU/definition binding')
  expected_name={'Rare Players':'RARE PLAYERS PACK','Premium Gold Players':'PREMIUM GOLD PLAYERS PACK','Jumbo Premium Gold':'JUMBO PREMIUM GOLD PACK','Mega':'MEGA PACK','Jumbo Rare Players':'JUMBO RARE PLAYERS PACK'}.get(label,label+' Pack')
  if DEFINITIONS[binding['definition']]['name']!=expected_name:raise ValueError('Pack label/definition disagreement')
  seen.add(binding['product_id'])
  rows.append({'product_id':binding['product_id'],'definition':binding['definition'],
               'coin_price':table[label]['coin_price'],'repeatable':True,'purchase_limit':1,
               'featured':True,'provenance':'revival_policy'})
 return {'persona_id':1,'products':rows}

def latest_projection(*,backend_only=False):
 return projection(LATEST_POLICY,backend_only=backend_only)
