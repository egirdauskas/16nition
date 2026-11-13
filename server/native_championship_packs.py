"""Backend-only title packs from supported definitions and the approved table."""
import hashlib,json
from .revival_rewards import load_reward_policy,POLICY
from .local_packs import DEFINITIONS
VERSION='backend_championship_packs_v1'
BINDINGS={'Bronze':'revival_bronze_mixed_v1','Premium Bronze':'revival_premium_bronze_mixed_v1',
          'Silver':'revival_silver_mixed_v1','Premium Silver':'revival_premium_silver_mixed_v1'}
VERSION_V2='backend_championship_packs_v2'
BINDINGS_V2={**BINDINGS,'Gold':'revival_gold_mixed_v1','Premium Gold':'revival_premium_gold_mixed_v1'}
VERSION_V3='backend_championship_packs_v3'
BINDINGS_V3={**BINDINGS_V2,'Rare Players':'revival_rare_players_v1'}
VERSION_V4='backend_championship_packs_v4'
BINDINGS_V4={**BINDINGS_V3,'Premium Gold Players':'revival_premium_gold_players_v3'}
VERSION_V5='backend_championship_packs_v5'
BINDINGS_V5={**BINDINGS_V4,'Jumbo Premium Gold':'revival_jumbo_premium_gold_mixed_v1','Mega':'revival_mega_mixed_v1'}
VERSION_V6='backend_championship_packs_v6'
VERSION_V7='backend_championship_packs_v7'
VERSION_V8='backend_championship_packs_v8'
VERSION_V9='backend_championship_packs_v9'

def snapshot(division,definition):
 from .native_season_completion import digest,encode
 if type(division) is not int or not 1<=division<=10:raise ValueError('Invalid title pack division')
 policy=load_reward_policy();label=policy['divisions'][str(division)]['season']['CHAMPIONSHIP']['pack_label']
 from .pack_policy import all_tier_special_bindings,expanded_consumable_bindings,filtered_consumable_bindings,crowd_filtered_consumable_bindings
 specials=all_tier_special_bindings()
 expanded=expanded_consumable_bindings()
 filtered=filtered_consumable_bindings()
 crowd_filtered=crowd_filtered_consumable_bindings()
 crowd_cleaned=label in crowd_filtered and crowd_filtered[label]==definition and crowd_filtered[label]!=filtered[label]
 cleaned=label in filtered and filtered[label]==definition and filtered[label]!=expanded[label]
 extended=label in expanded and expanded[label]==definition and expanded[label]!=specials[label]
 new=label in specials and specials[label]==definition
 parity=False
 if not (crowd_cleaned or cleaned or extended or new or BINDINGS_V5.get(label)==definition):
  from .reward_store_parity import policy as parity_policy
  parity=parity_policy()['bindings'][label]['definition']==definition
  if not parity:raise ValueError('Unsupported or substituted title pack definition')
 # Keep every already admitted D10–D7 source snapshot byte-compatible. Only
 # newly supported Gold/Premium Gold titles use v2; no CLI/native activation.
 version='backend_championship_packs_v10' if parity and not (crowd_cleaned or cleaned or extended or new) else VERSION_V9 if crowd_cleaned else VERSION_V8 if cleaned else VERSION_V7 if extended else VERSION_V6 if new else VERSION if label in BINDINGS else VERSION_V2 if label in BINDINGS_V2 else VERSION_V3 if label in BINDINGS_V3 else VERSION_V4 if label in BINDINGS_V4 else VERSION_V5
 return {'version':version,'table_sha256':hashlib.sha256(POLICY.read_bytes()).hexdigest(),
         'division':division,'pack_label':label,'definition':definition,
         'definition_sha256':digest(encode(DEFINITIONS[definition]))}

def validate_snapshot(start):
 if type(start) is not dict or json.dumps(start,sort_keys=True)!=json.dumps(snapshot(start.get('division'),start.get('definition')),sort_keys=True):
  raise ValueError('Title pack source snapshot changed')
 return start

def delivery(start):
 validate_snapshot(start)
 return {'definition':start['definition'],'definition_sha256':start['definition_sha256'],'classification':'isolated_transport_test'}

def validate(state):
 matches={m['id']:m for m in state['matches']}
 for source in ([state['active_match']] if state['active_match'] else [])+state['matches']:
  start=source.get('championship_pack_start')
  if start is None and 'championship_pack_start' not in source:continue
  validate_snapshot(start);request=json.loads(bytes.fromhex(source['create_body_hex']))
  if source.get('pack_entitlement_policy_version')!='backend_pack_entitlement_test_v1' or request['divisionId']!=11-start['division']:
   raise ValueError('Title pack source division/authorization mismatch')
 for completion in state['completions']:
  start=completion.get('championship_pack_start');grant=completion.get('season_pack_delivery')
  source=matches.get(completion['receipt_id'])
  if not source:raise ValueError('Completion lacks native match source')
  expected_start=source.get('championship_pack_start')
  if expected_start is None:
   if start is not None or grant is not None:raise ValueError('No retroactive title pack grant')
   continue
  if start!=expected_start or completion.get('pack_entitlement_policy_version')!='backend_pack_entitlement_test_v1':
   raise ValueError('Title pack completion differs from accepted source')
  from .native_season_coin_rewards import validate_final_source
  validate_final_source(source,completion,start['division'])
  from .season_revival_policy import load_policy
  outcome=load_policy().for_division(start['division']).evaluate(source['fixture'],source['points_after'])
  if completion['outcome']!=outcome or not outcome['complete']:raise ValueError('Title pack completion outcome changed')
  expected=delivery(start) if outcome['preview_band']=='CHAMPIONSHIP' else None
  if grant!=expected:raise ValueError('Only genuine championship has a resolved title pack')
