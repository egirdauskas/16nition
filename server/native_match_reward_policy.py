"""Approved coin quotes; XP, pack and Store effects retain their own coordinators."""
import hashlib,json
from pathlib import Path
from .local_profile import validate_credits

def load_reward_policy(path):
 value=json.loads(Path(path).read_text())
 if value.get('version')=='native_match_coins_v1':
  fixed={'classification':'revival_policy','version':'native_match_coins_v1','scope':'isolated_native_simulation',
         'default_enabled':False,'table_version':'offline_rewards_v1','coin_table_already_15x':True,
         'level_step_percent':2,'snapshot':'at_create','rounding':'floor_integer_coins',
         'season_rewards_enabled':False,'xp_enabled':False,'pack_rewards_enabled':False}
  if set(value)!=set(fixed)|{'rationale'}:raise ValueError('Unexpected coin-only policy fields')
  if any(type(value[k]) is not type(v) or value[k]!=v for k,v in fixed.items()) or not isinstance(value['rationale'],str) or not value['rationale']:
   raise ValueError('Unsupported coin-only reward activation')
  from .revival_rewards import match_coin_quote
  match_coin_quote(10,'W',0)
  return value
 if set(value)!={'classification','version','scope','default_enabled','match_coins','season_rewards_enabled','xp_enabled','rationale'}:raise ValueError('Unexpected native reward policy fields')
 if (value['classification']!='revival_policy' or value['version']!='native_match_reward_test_v1' or
     value['scope']!='isolated_native_simulation' or value['default_enabled'] is not False or
     value['season_rewards_enabled'] is not False or value['xp_enabled'] is not False or
     type(value['match_coins']) is not int or not 1<=value['match_coins']<=100 or type(value['rationale']) is not str):
  raise ValueError('Only bounded isolated native test coins supported')
 return value

def reward_marker(account,state,current,policy):
 from . import gameplay_release
 from . import fresh_account_runtime as fresh
 fresh_selected = fresh.selected(account)
 if fresh_selected or gameplay_release.selected(account):
  if fresh_selected:
   configuration = fresh.validate(account)
   if state['account_id'] != configuration['account_id']:
    raise ValueError('Fresh coin journal belongs to another setup owner')
   if any(m['cycle_id'] == state['cycle']['id'] and m['fixture'] == current.round_number
          for m in state['matches']):
    raise ValueError('Fresh coin source fixture already consumed')
  else:
   gameplay_release.validate(account)
  if policy['version']!='native_match_coins_v1':raise ValueError('Release supports approved match coins only')
  source=state.get('active_match')
  if source and (source['cycle_id']!=state['cycle']['id'] or source['fixture']!=current.round_number):raise ValueError('Release coin source differs')
  return {'profile_before_sha256':hashlib.sha256((account/'profile.json').read_bytes()).hexdigest()}
 marker_path=account/'native-reward-lab.json'
 if marker_path.is_symlink():raise ValueError('Reward marker alias refused')
 marker=json.loads(marker_path.read_text())
 if set(marker)!={'schema','classification','policy_version','account_id','persona_id','cycle_id','fixture_index','profile_before_sha256'}:
  raise ValueError('Invalid isolated reward authorization marker')
 coins_only=policy['version']=='native_match_coins_v1'
 if (type(marker['schema']) is not int or marker['schema']!=1 or marker['classification']!=('isolated_native_match_coins' if coins_only else 'isolated_native_reward_test') or
     marker['policy_version']!=policy['version'] or marker['account_id']!=state['account_id'] or
     type(marker['persona_id']) is not int or marker['persona_id']!=state['account_identity']['persona_id'] or
     marker['cycle_id']!=state['cycle']['id'] or type(marker['fixture_index']) is not int or
     not 1<=marker['fixture_index']<=(10 if coins_only else 9) or current.round_number!=marker['fixture_index']):
  raise ValueError('Reward limited to explicitly pinned isolated account/cycle/fixture')
 if any(m['cycle_id']==marker['cycle_id'] and m['fixture']==marker['fixture_index'] for m in state['matches']):
  raise ValueError('Reward source fixture already consumed')
 profile=(account/'profile.json').read_bytes()
 if hashlib.sha256(profile).hexdigest()!=marker['profile_before_sha256']:
  # A genuine completed GameReport precedes FUT End. Accept only its exact
  # journaled XP-only profile image; purchases or other changes still refuse.
  report=(state.get('active_match') or {}).get('native_xp_report')
  if (not report or report['profile_before_sha256']!=marker['profile_before_sha256'] or
      report['profile_after_sha256']!=hashlib.sha256(profile).hexdigest()):raise ValueError('Pinned wallet changed before award; refusing overwrite')
 return marker

def reward_quote(account,state,current,policy,result=None):
 marker=reward_marker(account,state,current,policy)
 profile=(account/'profile.json').read_bytes()
 if state['active_match'].get('difficulty_reward_start'):
  from .difficulty_rewards import source_coin_quote,VERSION
  calculation=source_coin_quote(state['active_match'],result)
  before=json.loads(profile)['credits']
  return {'policy_version':VERSION,'classification':'revival_policy','quote':calculation,
          'amount':calculation['amount'],'credits_before':before,'credits_after':validate_credits(before+calculation['amount']),
          'profile_before_sha256':hashlib.sha256(profile).hexdigest()}
 if policy['version']=='native_match_coins_v1':
  from .revival_rewards import match_coin_quote
  from .account_progression import level_state
  snapshot=state['active_match'].get('coin_reward_start')
  if (not snapshot or snapshot['policy_version']!=policy['version'] or snapshot['division']!=current.division_index or
      snapshot['level']!=level_state(snapshot['total_xp'])['level']):raise ValueError('Accepted creation coin snapshot required')
  calculation=match_coin_quote(snapshot['division'],result,snapshot['total_xp'])
  before=json.loads(profile)['credits']
  return {'policy_version':policy['version'],'classification':'revival_policy','quote':calculation,
          'amount':calculation['amount'],'credits_before':before,'credits_after':validate_credits(before+calculation['amount']),
          'profile_before_sha256':hashlib.sha256(profile).hexdigest()}
 before=json.loads(profile)['credits'];after=validate_credits(before+policy['match_coins'])
 return {'policy_version':policy['version'],'classification':'revival_policy_test_only',
         'amount':policy['match_coins'],'credits_before':before,'credits_after':after,
         'profile_before_sha256':marker['profile_before_sha256']}

def response_fields(amount):
 # EndOfGameHandler01049e90 is called at parent+20: response+28 matchCoins
 # becomes parent+16b8 Total, response+40 participation becomes+16a8 Bonus.
 # 00a586ec builds Bonus/Total/TOTW;00a6ca50 installs Bonus and Total-Bonus.
 # Using equal Total/participation leaves the other term0; no component summing.
 return {'matchCoins':amount,'participationAward':amount}
