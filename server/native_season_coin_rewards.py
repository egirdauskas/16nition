"""Prospective backend-only season coins using the existing native journal.

Defaults remain backend-only. The isolated native season-coin selector also
opts into a prospectively snapshotted Awards presentation candidate. A completion
must retain its accepted source snapshot and wallet projection; historical
completions cannot become eligible.
"""
import copy,hashlib,json,uuid
from .revival_rewards import POLICY,load_reward_policy
from .local_profile import validate_credits
VERSION='backend_native_season_coins_v1'
AWARDS_PROJECTION='native_total_and_participation_v1'
SEASON_PRIZE_PROJECTION='native_total_participation_and_season_prize_v2'
DIFFICULTY_VERSION='backend_native_season_coins_difficulty_v1'

def difficulty_snapshot(selected,*,awards_projection=False,season_prize_display=False):
 from .difficulty_rewards import snapshot as start_snapshot,season_quote
 if type(awards_projection) is not bool:raise ValueError('Explicit Awards projection selector required')
 start=start_snapshot(selected,1,0)
 outcomes={}
 for band in ('RELEGATION','MAINTENANCE','PROMOTION','CHAMPIONSHIP'):
  if (selected.division_index==10 and band=='RELEGATION') or (selected.division_index==1 and band=='PROMOTION'):
   outcomes[band]=None
  else:outcomes[band]=season_quote(start,band)['coins']
 value={'version':DIFFICULTY_VERSION,'table_version':start['version'],'table_sha256':start['policy_sha256'],
        'division':selected.division_index,'competition_reference':start['competition_reference'],'outcomes':outcomes}
 _projection(value,awards_projection,season_prize_display)
 return value

def snapshot(division,*,awards_projection=False,season_prize_display=False):
 if type(division) is not int or not 1<=division<=10:raise ValueError('Invalid season reward division')
 if type(awards_projection) is not bool:raise ValueError('Explicit Awards projection selector required')
 policy=load_reward_policy()
 value={'version':VERSION,'table_version':policy['version'],
         'table_sha256':hashlib.sha256(POLICY.read_bytes()).hexdigest(),'division':division,
         'outcomes':{band:entry['coins'] for band,entry in policy['divisions'][str(division)]['season'].items()}}
 _projection(value,awards_projection,season_prize_display)
 return value

def _projection(value,awards_projection,season_prize_display):
 if type(season_prize_display) is not bool or (season_prize_display and not awards_projection):
  raise ValueError('Season prize display requires explicit Awards projection')
 if awards_projection:
  value['native_awards_projection']=SEASON_PRIZE_PROJECTION if season_prize_display else AWARDS_PROJECTION

def validate_snapshot(value):
 if type(value) is not dict:raise ValueError('Season reward snapshot changed')
 projection=value.get('native_awards_projection')
 if projection not in (None,AWARDS_PROJECTION,SEASON_PRIZE_PROJECTION):raise ValueError('Unsupported native Awards projection')
 options={'awards_projection':projection is not None,'season_prize_display':projection==SEASON_PRIZE_PROJECTION}
 if value.get('version')==DIFFICULTY_VERSION:
  from .season_choices import definition,load_catalog
  from .season_choice_reference import snapshot as reference
  ref=value.get('competition_reference')
  if type(ref) is not dict or ref.get('competition_key') not in load_catalog():raise ValueError('Unknown season difficulty reference')
  selected=definition(load_catalog()[ref['competition_key']],ref.get('season_id'),ref.get('fixture_seed'))
  expected=difficulty_snapshot(selected,**options)
  if reference(selected)!=ref or json.dumps(value,sort_keys=True)!=json.dumps(expected,sort_keys=True):raise ValueError('Season difficulty snapshot changed')
  return value
 if json.dumps(value,sort_keys=True)!=json.dumps(snapshot(value.get('division'),**options),sort_keys=True):raise ValueError('Season reward snapshot changed')
 return value

def awards_response(start,outcome,match_coins):
 """Candidate revival presentation through the recovered Total/base consumer.

 01049e90 ->00a586ec ->00a6ca50 installs participation as completion, Total
 minus participation as the original generic result bonus. The separate
 seasonCoins field reaches GetFUTCoins().seasonPrize through response+34 ->
 parent+16c4 ->021c4df4, read by SeasonsPostmatchOptions. Version2 opts into
 that display field; version1 source receipts keep their exact old response.
 This projection never credits the wallet; match and season journals do that.
 """
 validate_snapshot(start)
 from .native_match_reward_policy import response_fields
 reply=response_fields(match_coins)
 if start.get('native_awards_projection') in (AWARDS_PROJECTION,SEASON_PRIZE_PROJECTION) and outcome['complete']:
  bonus=quote(start,outcome['preview_band'])['amount']
  reply['matchCoins']=validate_credits(match_coins+bonus)
  if start['native_awards_projection']==SEASON_PRIZE_PROJECTION:reply['seasonCoins']=bonus
 return reply

def quote(start,band):
 validate_snapshot(start)
 if band not in start['outcomes'] or start['outcomes'][band] is None:raise ValueError('Inapplicable season coin band')
 keys=('version','table_version','table_sha256','division')
 if start['version']==DIFFICULTY_VERSION:keys+=('competition_reference',)
 return {k:start[k] for k in keys}|{'band':band,'amount':start['outcomes'][band]}

def validate_final_source(match,completion,division):
 if match.get('native_match_forfeit'):
  from .native_match_forfeit_final import completion_base
  expected=completion_base(match,completion['policy_version'])[0]
  if completion!=expected or division!=match['native_xp_start']['division']:
   raise ValueError('Season bonus contradicts genuine final forfeit source')
  return
 from .season_completion_timing import source_outcome
 from .season_progression import advance
 body=bytes.fromhex(match['end_body_hex']);result=json.loads(body)
 score=[result['myMatchStats']['goals'],result['opponentMatchStats']['goals']]
 result_code={'WIN':'W','DRAW':'D','LOSS':'L'}.get(result['endReason'])
 if match.get('played_match'):
  report=match.get('native_xp_report')
  if not report or (report['observation']['score'],report['observation']['result'])!=(score,result_code):
   raise ValueError('Played season reward requires its matching authenticated report')
 recorded=completion['final_native_result'];anchor=completion['original_pre_final_state']
 played,points=advance(anchor['round_number']-1,anchor['user_points'],match['result'])
 if (match['provenance']!=('original_native_played' if match.get('played_match') else 'original_native_simulation') or match['cycle_id']!=completion['cycle_id'] or
     match['fixture']!=anchor['round_number'] or any(type(x) is not int for x in score) or score!=match['score'] or
     result_code!=match['result'] or
     ('W' if score[0]>score[1] else 'L' if score[0]<score[1] else 'D')!=match['result'] or
     points!=match['points_after'] or not completion['outcome']['complete'] or
     completion['outcome']!=source_outcome(match,division,points) or
     recorded['result']!=match['result'] or recorded['score']!=score or recorded['expected_points']!=points or
     recorded['expected_round']!=played+1 or recorded['native_end_body_sha256']!=hashlib.sha256(body).hexdigest()):
  raise ValueError('Season bonus contradicts genuine final source/outcome')

def validate(state):
 rewards=state.get('season_coin_rewards',[])
 if type(rewards) is not list:raise ValueError('Invalid season coin receipt collection')
 seen=set();sources=set();matches={m['id']:m for m in state['matches']}
 for m in ([state['active_match']] if state['active_match'] else [])+state['matches']:
  if 'season_coin_start' in m:validate_snapshot(m['season_coin_start'])
 eligible={}
 for completion in state['completions']:
  start=completion.get('season_coin_start');delivery=completion.get('season_coin_delivery')
  if start is None and delivery is None:continue
  validate_snapshot(start)
  match=matches.get(completion['receipt_id'])
  if (not match or match.get('season_coin_start')!=start or completion['status']!='committed'
      or start['division']!=completion['original_pre_final_state']['division_index']):raise ValueError('Season coins lack prospective source')
  validate_final_source(match,completion,start['division'])
  expected=quote(start,completion['outcome']['preview_band'])
  if type(delivery) is not dict or set(delivery)!={'quote','credits_before','profile_before_sha256'} or json.dumps(delivery['quote'],sort_keys=True)!=json.dumps(expected,sort_keys=True):
   raise ValueError('Invalid pending season coin delivery')
  validate_credits(delivery['credits_before']);checksum(delivery['profile_before_sha256'])
  eligible[completion['id']]=completion
 for reward in rewards:
  required={'id','source_id','source_match_id','account_id','persona_id','cycle_id','status','certification',
            'quote','amount','credits_before','credits_after','profile_before_sha256','profile_after_sha256'}
  if type(reward) is not dict or set(reward)!=required:raise ValueError('Invalid season coin receipt')
  source=eligible.get(reward['source_id'])
  if not source:raise ValueError('No retroactive or foreign season coin grant')
  delivery=source['season_coin_delivery']
  if (reward['id']!=str(uuid.uuid5(uuid.UUID(source['id']),'season-coins')) or
      reward['source_match_id']!=source['receipt_id'] or reward['cycle_id']!=source['cycle_id'] or
      reward['account_id']!=state['account_id'] or type(reward['persona_id']) is not int or
      reward['persona_id']!=state['account_identity']['persona_id'] or reward['status']!='committed' or
      reward['certification']!='backend_only' or reward['quote']!=delivery['quote'] or
      type(reward['amount']) is not int or reward['amount']!=delivery['quote']['amount'] or
      reward['credits_before']!=delivery['credits_before'] or
      reward['profile_before_sha256']!=delivery['profile_before_sha256'] or
      reward['credits_after']!=validate_credits(reward['credits_before']+reward['amount']) or
      reward['id'] in seen or reward['source_id'] in sources):raise ValueError('Season coin receipt/source mismatch')
  validate_credits(reward['credits_before']);validate_credits(reward['credits_after'])
  checksum(reward['profile_after_sha256']);seen.add(reward['id']);sources.add(reward['source_id'])

def checksum(value):
 if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('Invalid season wallet checksum')

def validate_reward_intent(before,final,images):
 """An independent reward append cannot rewrite its native completion."""
 from .native_season_completion import digest
 validate(final)
 old=before.get('season_coin_rewards',[]);new=final.get('season_coin_rewards',[])
 if (new[:len(old)]!=old or len(new)!=len(old)+1 or
     any(final[k]!=before[k] for k in before if k not in ('prepared','season_coin_rewards')) or
     len(images)!=1 or images[0]['name']!='profile.json'):raise ValueError('Invalid separate season coin intent')
 reward=new[-1];image=images[0];a=bytes.fromhex(image['before']);b=bytes.fromhex(image['after']);expected=json.loads(a)
 if expected['credits']!=reward['credits_before']:raise ValueError('Season reward before wallet mismatch')
 expected['credits']=reward['credits_after']
 if json.loads(b)!=expected or (digest(a),digest(b))!=(reward['profile_before_sha256'],reward['profile_after_sha256']):
  raise ValueError('Season reward changes unrelated profile or wallet')

def reward_image(state,source,raw):
 """Pure existing receipt/profile projection, also used by atomic final End."""
 from .native_season_completion import digest,encode
 delivery=source['season_coin_delivery'];profile=json.loads(raw)
 if digest(raw)!=delivery['profile_before_sha256'] or profile['credits']!=delivery['credits_before']:
  raise ValueError('Pending season coin wallet conflict; unrelated changes preserved')
 amount=delivery['quote']['amount'];profile['credits']=validate_credits(profile['credits']+amount);data=encode(profile)
 reward={'id':str(uuid.uuid5(uuid.UUID(source['id']),'season-coins')),'source_id':source['id'],
         'source_match_id':source['receipt_id'],'account_id':state['account_id'],
         'persona_id':state['account_identity']['persona_id'],'cycle_id':source['cycle_id'],
         'status':'committed','certification':'backend_only','quote':copy.deepcopy(delivery['quote']),
         'amount':amount,'credits_before':delivery['credits_before'],'credits_after':profile['credits'],
         'profile_before_sha256':digest(raw),'profile_after_sha256':digest(data)}
 return data,reward

def recover(coordinator,state):
 """Reuse the coordinator's locks, prepared images and atomic journal commit."""
 from .native_season_completion import digest,encode
 consumed={r['source_id'] for r in state.get('season_coin_rewards',[])}
 for source in state['completions']:
  delivery=source.get('season_coin_delivery')
  if delivery is None or source['id'] in consumed:continue
  raw=(coordinator.account/'profile.json').read_bytes();data,reward=reward_image(state,source,raw)
  final=copy.deepcopy(state);final.setdefault('season_coin_rewards',[]).append(reward)
  return coordinator._transaction(state,final,[coordinator._image('profile.json',data)])
 return state
