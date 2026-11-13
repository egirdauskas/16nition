"""Season-ending QUIT in the existing native journal; no match reward.

An emitted session-bound TerminationReason3 report is retained when available.
Early stock Sim forfeits may omit it. Its partial score never replaces the loss. Existing season
policy determines the separate season bonus and next competition eligibility.
"""
import copy,json,uuid
from .native_match_forfeit import KEY,REPORT,VERSION,validate_report,decode
from .native_atomic_match import pinned,sha
from .native_season_completion import encode


def completion_base(source,policy_version):
    if source.get(REPORT):validate_report(source)
    raw,season=pinned(source);profile=json.loads(raw);anchor=json.loads(season)['current']
    from .season_completion_timing import source_outcome
    outcome=source_outcome(source,anchor['division_index'],anchor['user_points'])
    if not outcome['complete'] or outcome['preview_band']=='CHAMPIONSHIP':
        # An already-secured title cannot first be earned by an unchanged-points
        # loss under the admitted early-completion policy.
        raise ValueError('QUIT cannot newly secure a championship')
    body=bytes.fromhex(source[KEY]['body_hex']);decode(body)
    observation=dict(result='L',score=None,expected_points=anchor['user_points'],
        expected_round=source['fixture']+1,native_end_body_sha256=sha(body))
    completion=dict(id=str(uuid.uuid5(uuid.UUID(source['id']),'season-completion')),
        cycle_id=source['cycle_id'],receipt_id=source['id'],policy_version=policy_version,outcome=outcome,
        original_pre_final_state=anchor,final_native_result=observation,
        next_cycle_id=str(uuid.uuid5(uuid.UUID(source['id']),'next-season-cycle')),status='committed',rewards_enabled=False)
    profile['division_offline']=outcome['proposed_next_division'];data=encode(profile)
    if source.get('season_coin_start'):
        from .native_season_coin_rewards import quote
        completion['season_coin_start']=copy.deepcopy(source['season_coin_start'])
        completion['season_coin_delivery']=dict(quote=quote(source['season_coin_start'],outcome['preview_band']),
            credits_before=profile['credits'],profile_before_sha256=sha(data))
    return completion,data


def parts(state,source):
    completion,data=completion_base(source,state['policy_version'])
    response={'seasonEndResult':completion['outcome']['preview_band']};reward=None
    if source.get('season_coin_start'):
        from .native_season_coin_rewards import reward_image,awards_response
        data,reward=reward_image(state,completion,data)
        response=awards_response(source['season_coin_start'],completion['outcome'],0)|response
    return completion,data,reward,response


def proposal(c,before,target,body,*,football_before=None):
    source=before['active_match']
    after=copy.deepcopy(before);after['prepared']=None;source=after['active_match'];after['active_match']=None
    source[KEY]=dict(version=VERSION,target=target,body_hex=body.hex())
    completion,data,reward,response=parts(before,source)
    source.update(status='committed',end_body_hex=body.hex(),result='L',score=None,
        points_after=completion['original_pre_final_state']['user_points'],response=response,
        provenance='original_native_played_forfeit' if source.get('played_match') else 'original_native_simulation_forfeit',
        reward_coins=0,reward_xp=0,reward=None,native_atomic_final=True)
    after['matches'].append(source);after['completions'].append(completion)
    if reward is not None:after.setdefault('season_coin_rewards',[]).append(reward)
    # No fixture/title pack image: forfeiture cannot earn either entitlement.
    images=[dict(name='profile.json',before=pinned(source)[0].hex(),after=data.hex()),
        dict(name='seasons.json',before=pinned(source)[1].hex(),
             after=encode(dict(persona_id=before['account_identity']['persona_id'],current=None)).hex())]
    from .injury_effects import match_image as training_image
    expired=training_image(c,source,before_raw=football_before)
    if expired is not None:images.append(expired)
    from .native_division_season_identity import next_id
    after['cycle']=dict(id=completion['next_cycle_id'],division=completion['outcome']['proposed_next_division'],
        season_id=next_id(source,completion['outcome']),status='awaiting_native_initialization',
        previous_cycle_id=source['cycle_id'],initial_native_anchor=None)
    from .season_choice_reference import snapshot,archive_unreferenced
    from .season_choice_pending import KEY as PENDING,snapshot as pending
    definition=c.stores()[0].definition
    if snapshot(definition) is not None or source.get('season_choice_handoff'):
        if snapshot(definition) is None:after['season_definition_history']=archive_unreferenced(definition,after)
        after['cycle'][PENDING]=pending(source,after.get('season_definition_history'))
    else:
        value=json.loads((c.account/'definition.json').read_bytes())
        value.update(division_index=after['cycle']['division'],season_id=after['cycle']['season_id'])
        images.append(c._image('definition.json',encode(value)))
    return dict(operation='match_forfeit_final',response=response,after=after,images=images)


def validate_completion(source,completion,state):
    expected,data,reward,response=parts(state,source)
    if completion!=expected or source['response']!=response:
        raise ValueError('Final forfeit completion/presentation differs from its pinned source')
    rewards=[r for r in state.get('season_coin_rewards',[]) if r['source_id']==completion['id']]
    if rewards!=([reward] if reward is not None else []):
        raise ValueError('Final forfeit must commit exactly its separate season bonus')


def validate_source(source,state):
    completion=next((c for c in state['completions'] if c['receipt_id']==source['id']),None)
    if (completion is None or source.get('end_body_hex')!=source[KEY]['body_hex'] or source.get('result')!='L'
            or source.get('score') is not None or type(source.get('reward_coins')) is not int or source['reward_coins']!=0
            or type(source.get('reward_xp')) is not int or source['reward_xp']!=0 or source.get('reward') is not None
            or source.get('native_atomic_final') is not True or source.get('native_atomic_save') is not None
            or source.get('atomic_pack',{}).get('grant') is not None
            or source.get('provenance')!=('original_native_played_forfeit' if source.get('played_match') else 'original_native_simulation_forfeit')
            or source.get('points_after')!=completion['original_pre_final_state']['user_points']):
        raise ValueError('Invalid zero-match-reward final forfeiture')
    validate_completion(source,completion,state)


def validate_intent(c,before,after,images):
    added=after['matches'][len(before['matches']):]
    if not added or not added[0].get(KEY) or not added[0].get('native_atomic_final'):return False
    old=before['active_match']
    if not old or len(added)!=1 or old['id']!=added[0]['id']:
        raise ValueError('Terminal QUIT requires its current accepted source')
    # Recompute against original pinned images even if a journal image has
    # already installed. The journal refuses conflicting on-disk images.
    from .training_expiry import before_image as training_before
    source=added[0];expected=proposal(c,before,source[KEY]['target'],bytes.fromhex(source[KEY]['body_hex']),football_before=training_before(images))
    if expected['after']!=after or expected['images']!=images:
        raise ValueError('Terminal QUIT changes unrelated state')
    validate_source(source,after);return True
