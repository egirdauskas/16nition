"""Source-bound original QUIT; the original loss save is the commit authority.

No score is invented. QUIT contains only player proposals, which are ignored.
TerminationReason3 reports carry actual partial stats and never award XP.
"""
import copy,json
from pathlib import Path
from .game_auth import SID
from .native_played_protocol import END_PATH
from .native_simulation_protocol import END_PATH as SIM_END_PATH
from .native_match_session import REPORT_PATH,NS,session_id

ROOT=Path(__file__).resolve().parents[1]
VERSION='native_match_forfeit_v1'
KEY='native_match_forfeit'
REPORT='native_forfeit_report'
ACCOUNT=None


def configure(account=None):
    global ACCOUNT
    ACCOUNT=None
    if account is None:return
    account=Path(account).resolve()
    from . import match_forfeit_release as release
    from .fresh_account_runtime import selected as fresh_selected
    if account==release.REAL:release.validate(account)
    elif not fresh_selected(account) and (
        ROOT/'reports' not in account.parents or account.name!='isolated-account'
        or not (account/'.lab-snapshot.json').is_file()
    ):
        raise ValueError('Uncertified match forfeiture requires an archived isolated account')
    ACCOUNT=account


def selected(account):return ACCOUNT==Path(account).resolve()


def decode(body):
    from .native_simulation_protocol import _unique
    value=json.loads(body,object_pairs_hook=_unique)
    if type(value) is not dict or set(value)!={'endReason','items'} or value['endReason']!='QUIT':
        raise ValueError('Not the captured original QUIT shape')
    items=value['items']
    if type(items) is not list or not 11<=len(items)<=18:raise ValueError('Invalid QUIT player roster')
    for item in items:
        # Same item boundary as the existing DestroyMatch validator: verify
        # ownership IDs, never apply proposed stats/condition.1252 genuinely
        # includes an optional goals member while forfeiting a1-0 Sim lead.
        if (type(item) is not dict or type(item.get('id')) is not int
                or not 0<item['id']<=0x7fffffffffffffff):
            raise ValueError('Invalid original QUIT player proposal')
    ids=[item['id'] for item in items]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate QUIT player identity')
    return ids


def validate_source(source,state,coordinator=None):
    if source.get(REPORT):validate_report(source,coordinator)
    marker=source.get(KEY)
    if marker is None:return False
    expected_target=END_PATH if source.get('played_match') else SIM_END_PATH
    if (type(marker) is not dict or set(marker)!={'version','target','body_hex'} or marker['version']!=VERSION
            or marker['target']!=expected_target or not source.get('atomic_match')
            or not source.get('native_xp_start') or source.get('native_xp_report') or source.get('atomic_end')
            or source['status'] not in ('playing','committed','aborted')):
        raise ValueError('Invalid original forfeit source')
    body=bytes.fromhex(marker['body_hex']);decode(body)
    from .native_atomic_match import pinned
    profile_raw,season_raw=pinned(source);profile=json.loads(profile_raw);season=json.loads(season_raw)
    original=season['current'];create=json.loads(bytes.fromhex(source['create_body_hex']))
    if (any(profile[k]!=state['account_identity'][k] for k in ('persona_id','identity_pid','user_id'))
            or season['persona_id']!=profile['persona_id'] or original['round_number']!=source['fixture']
            or create['seasonId']!=original['season_id'] or create['divisionId']!=11-original['division_index']
            or create['type']!='OFFLINE' or source['native_xp_start']['total_xp']!=profile.get('revival_total_xp',0)
            or source['native_xp_start']['division']!=original['division_index']
            or source['policy_version']!=state['policy_version']):
        raise ValueError('Forfeit lost its original account/fixture snapshot')
    if coordinator is not None and source['status']=='playing':
        from .match_roster import match_players
        if set(decode(body))!=match_players(coordinator.stores()[1].load(1)):
            raise ValueError('Forfeit stage lost its original owned match roster')
    if source['status']=='committed':
        if source.get('native_atomic_final'):
            from .native_match_forfeit_final import validate_source as validate_final
            validate_final(source,state)
            return True
        saved=source.get('native_atomic_save')
        if (source.get('end_body_hex')!=marker['body_hex'] or source.get('result')!='L' or source.get('score') is not None
                or source.get('reward_coins')!=0 or source.get('reward_xp')!=0 or source.get('reward') is not None
                or source.get('response')!={} or source.get('native_atomic_final') or
                type(source.get('reward_coins')) is not int or type(source.get('reward_xp')) is not int
                or source.get('provenance')!=('original_native_played_forfeit' if source.get('played_match') else 'original_native_simulation_forfeit')
                or source.get('atomic_pack',{}).get('grant') is not None
                or type(saved) is not dict or set(saved)!={'target','body_hex'}):
            raise ValueError('Forfeit cannot become a scored or rewarded completion')
        before=json.loads(bytes.fromhex(source['atomic_match']['season_before_hex']))['current']
        value=json.loads(bytes.fromhex(saved['body_hex']))
        from .season_blob import validated_progress,decode_envelope
        import base64
        if (set(value)!={'round','data'} or type(value['round']) is not int
                or value['round']!=source['fixture']+1 or before['round_number']!=source['fixture']
                or source['points_after']!=before['user_points']
                or validated_progress(decode_envelope(base64.b64decode(value['data'],validate=True)),value['round'])!=before['user_points']
                or saved['target']!=f"/ut/game/fifaworldmobile/season/{before['season_id']}/division/{11-before['division_index']}/user"):
            raise ValueError('Forfeit lost its original loss save')
        if coordinator is not None:
            from .season_choice_reference import resolve
            definition=resolve(coordinator.stores()[0].definition,source,state.get('season_definition_history'))
            from .local_seasons import CurrentSeason,SeasonStore
            from .offline_seasons_protocol import parse_season_save
            class Original(SeasonStore):
                def load(self):return CurrentSeason(**before)
            current=parse_season_save(bytes.fromhex(saved['body_hex']),Original(coordinator.account/'seasons.json',definition))
            from .season_compatibility import genuine_progression
            if genuine_progression(CurrentSeason(**before),current,definition)['result']!='L':
                raise ValueError('Original forfeit save is not a loss')
    return True


def proposal(c,state,method,target,headers,body):
    if not selected(c.account) or not c.native_atomic_matches:return None
    source=state['active_match']
    if target==REPORT_PATH and method=='POST':
        from .native_match_session import inspect_report
        from .native_played_protocol import report_start_time
        candidates=([source] if source else [])+[s for s in reversed(state['matches']) if s.get(KEY)]
        for owner in candidates:
            if not owner.get('atomic_match') or owner['status'] not in ('playing','committed'):continue
            observed=inspect_report(method,target,headers,body,c,expected_session=session_id(owner['id']),
                expected_start_time=report_start_time(owner),allow_forfeit=True)
            if observed is not None and observed.get('termination_reason')==3:
                if owner is source and not owner.get(KEY) and terminal(owner):
                    if owner.get('native_xp_report') or owner.get('atomic_end'):
                        raise ValueError('Forfeit report conflicts with normal completion')
                    marker=dict(target=target,body_hex=body.hex())
                    if owner.get(REPORT):
                        if owner[REPORT]!=marker:raise ValueError('Conflicting final forfeit report')
                    else:
                        from .native_atomic_match import require_unchanged
                        require_unchanged(c,owner)
                        after=copy.deepcopy(state);after['prepared']=None
                        after['active_match'][REPORT]=marker
                        return dict(operation='match_forfeit_report_stage',response_xml=f'<Response xmlns="{NS}"/>',after=after,images=[])
                return dict(operation='match_forfeit_report',response_xml=f'<Response xmlns="{NS}"/>')
        return None
    if method=='PUT' and target in (END_PATH,SIM_END_PATH):
        try:decode(body)
        except (ValueError,TypeError,KeyError):return None
        if (headers.get(b'host')!=b'10.0.2.2:18081' or headers.get(b'x-ut-sid')!=SID.encode()
                or headers.get(b'content-length')!=str(len(body)).encode() or headers.get(b'content-type')!=b'application/json'):
            return None
        if source is None:
            prior=next((s for s in reversed(state['matches']) if
                (s.get(KEY,{}).get('target'),s.get(KEY,{}).get('body_hex'))==(target,body.hex())),None)
            return dict(operation='match_forfeit_end_retry',response=prior['response']) if prior else None
        if (source['status']!='playing' or bool(source.get('played_match'))!=(target==END_PATH) or not source.get('atomic_match')
                or source.get('native_xp_report') or source.get('atomic_end')):
            raise ValueError('QUIT needs its unfinished original match mode')
        if source.get(KEY):
            if source[KEY]['body_hex']!=body.hex():raise ValueError('Conflicting QUIT retry')
            return dict(operation='match_forfeit_end_retry',response={})
        from .native_atomic_match import require_unchanged
        require_unchanged(c,source)
        season,football,current=c._anchor(state)
        from .match_roster import match_players
        if set(decode(body))!=match_players(football.load(1)):raise ValueError('QUIT contains a foreign or incomplete match roster')
        from .injury_effects import validate_end as validate_injury_end
        validate_injury_end(source,body)
        from .season_completion_timing import source_outcome
        if source_outcome(source,current.division_index,current.user_points,season_policy=c.policy)['complete']:
            if source.get(REPORT):validate_report(source,c)
            from .native_match_forfeit_final import proposal as final_proposal
            return final_proposal(c,state,target,body)
        after=copy.deepcopy(state);after['prepared']=None
        after['active_match'][KEY]=dict(version=VERSION,target=target,body_hex=body.hex())
        return dict(operation='match_forfeit_end',response={},after=after,images=[])
    if source and source.get(KEY) and method=='PUT' and target.startswith('/ut/game/fifaworldmobile/season/'):
        from .native_atomic_match import valid_save_owner,require_unchanged
        if not valid_save_owner(method,headers,body):return None
        require_unchanged(c,source);season,_=c.stores();before=season.load()
        expected=f'/ut/game/fifaworldmobile/season/{before.season_id}/division/{11-before.division_index}/user'
        if target!=expected:return None
        from .offline_seasons_protocol import parse_season_save
        current=parse_season_save(body,season).validate(season.definition)
        from .season_compatibility import genuine_progression
        if genuine_progression(before,current,season.definition)['result']!='L':raise ValueError('QUIT requires the original loss save')
        return build_final(c,state,target,body,current)
    return None


def build_final(c,before,target,body,current,*,football_before=None):
    from dataclasses import asdict
    from .native_season_completion import encode
    after=copy.deepcopy(before);after['prepared']=None;source=after['active_match'];after['active_match']=None
    source.update(status='committed',end_body_hex=source[KEY]['body_hex'],result='L',score=None,
        points_after=current.user_points,response={},
        provenance='original_native_played_forfeit' if source.get('played_match') else 'original_native_simulation_forfeit',reward_coins=0,reward_xp=0,
        reward=None,native_atomic_save=dict(target=target,body_hex=body.hex()))
    after['matches'].append(source)
    images=[dict(name='seasons.json',before=source['atomic_match']['season_before_hex'],
        after=encode(dict(persona_id=before['account_identity']['persona_id'],current=asdict(current))).hex())]
    from .injury_effects import match_image as training_image
    expired=training_image(c,source,before_raw=football_before)
    if expired is not None:images.append(expired)
    return dict(operation='match_forfeit_save',response={},after=after,images=images)


def validate_intent(c,before,after,images):
    old=before['active_match'];new=after['active_match']
    if not old:return False
    from .native_match_forfeit_final import validate_intent as final_intent
    if final_intent(c,before,after,images):return True
    if new and new.get(REPORT) and not old.get(REPORT):
        expected=copy.deepcopy(before);expected['prepared']=None;expected['active_match'][REPORT]=new[REPORT]
        if after!=expected or images or not terminal(new):raise ValueError('Final forfeit report changes unrelated state')
        validate_report(new,c);return True
    if new and new.get(KEY) and not old.get(KEY):
        expected=copy.deepcopy(before);expected['prepared']=None;expected['active_match'][KEY]=new[KEY]
        if after!=expected or images:raise ValueError('QUIT stage changes unrelated state')
        validate_source(new,after,c);return True
    added=after['matches'][len(before['matches']):]
    if not old.get(KEY) or not added or not added[0].get(KEY):return False
    if len(added)!=1 or new is not None:raise ValueError('Forfeit must consume exactly its active source')
    if (c.account/'profile.json').read_bytes().hex()!=old['atomic_match']['profile_before_hex']:
        raise ValueError('Forfeit recovery conflicts with its original profile')
    from .local_seasons import CurrentSeason
    saved=added[0]['native_atomic_save'];image=next((i for i in images if i['name']=='seasons.json'),None)
    if image is None:raise ValueError('Forfeit lacks original season image')
    current=CurrentSeason(**json.loads(bytes.fromhex(image['after']))['current'])
    from .training_expiry import before_image as training_before
    expected=build_final(c,before,saved['target'],bytes.fromhex(saved['body_hex']),current,football_before=training_before(images))
    if after!=expected['after'] or images!=expected['images']:raise ValueError('Forfeit commit changes unrelated state')
    if image['before']!=old['atomic_match']['season_before_hex']:raise ValueError('Forfeit recovery conflicts with its original anchor')
    validate_source(added[0],after,c);return True


def terminal(source):
    from .native_atomic_match import pinned
    from .season_completion_timing import source_outcome
    current=json.loads(pinned(source)[1])['current']
    return source_outcome(source,current['division_index'],current['user_points'])['complete']


def validate_report(source,c=None):
    import xml.etree.ElementTree as ET
    from .native_played_protocol import report_start_time
    marker=source[REPORT]
    if type(marker) is not dict or set(marker)!={'target','body_hex'} or marker['target']!=REPORT_PATH or not terminal(source):
        raise ValueError('Invalid terminal forfeit report marker')
    body=bytes.fromhex(marker['body_hex']);root=ET.fromstring(body)
    tag=lambda name:'{'+NS+'}'+name
    if (root.tag!=tag('GameReport') or root.findtext(tag('MatchSessionId'))!=str(session_id(source['id']))
            or root.findtext(tag('TerminationReason'))!='3' or root.findtext(tag('MatchStartTime'))!=report_start_time(source)):
        raise ValueError('Final forfeit requires its authentic terminated session')
    if c is not None:
        from .native_match_session import inspect_report
        from .local_profile import load_profile
        p=load_profile(c.account/'profile.json')
        headers={b'host':b'10.0.2.2:18081',b'securitytoken':p.victory_security_token.encode(),b'userid':p.user_id.encode(),
            b'content-type':b'text/xml;charset=utf-8',b'content-length':str(len(body)).encode()}
        if inspect_report('POST',REPORT_PATH,headers,body,c,expected_session=session_id(source['id']),
                expected_start_time=report_start_time(source),allow_forfeit=True) is None:
            raise ValueError('Invalid original terminal partial report')
