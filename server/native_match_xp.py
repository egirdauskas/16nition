"""Prospective GameReport XP using the existing native season recovery journal.

786 proves that GameReport precedes FUT DestroySim. XP therefore belongs to the
authenticated completed report, while standings still require the later native
End and opaque save. No coins, packs or retrospective grants are issued here.
"""
import copy,hashlib,json,uuid
from .account_progression import level_state,quote,load_progression_policy
from .native_match_session import inspect_report,session_id,NS,REPORT_PATH
from .local_profile import load_profile
from .native_played_protocol import report_start_time

VERSION='native_match_xp_v1'

def sha(raw):return hashlib.sha256(raw).hexdigest()

def snapshot(profile,division):
    total=profile.revival_total_xp or 0
    return {'version':VERSION,'progression_policy_version':'account_progression_v1',
            'total_xp':total,'level':level_state(total)['level'],'division':division}

def validate_start(start):
    if (type(start) is not dict or set(start)!={'version','progression_policy_version','total_xp','level','division'} or
        start['version']!=VERSION or start['progression_policy_version']!='account_progression_v1' or
        type(start['division']) is not int or not 1<=start['division']<=10 or
        type(start['level']) is not int or start['level']!=level_state(start['total_xp'])['level']):
        raise ValueError('Invalid prospective native XP snapshot')

def response(calculation, level_start=None):
    # Original XMLMatchReward ->00300fa0 ->SummaryInfo ->00a6c9e4.
    # Coin terms stay at constructor0 so this separate message cannot add a
    # second copy of FUT match coins. Level-up CoinReward is sent only for
    # matches created with the XP-004 level reward snapshot (level_start).
    xp=calculation['xp'];before=calculation['start']['level'];after=calculation['after']['level']
    if xp>0xffff or after>0xffff:raise ValueError('Native DTO wire range exceeded; backend XP remains unbounded')
    reward=''
    if level_start is not None and after!=before:
        from .level_rewards import quote as level_quote,level_up_xml
        reward=level_up_xml(level_quote(level_start,before,after))
    level=(f'<LevelUpInfo>{reward}<CurrentLevel>{after}</CurrentLevel><PreviousLevel>{before}</PreviousLevel></LevelUpInfo>'
           if after!=before else '')
    return f'<Response xmlns="{NS}">{level}<MatchReward><Experience>{xp}</Experience></MatchReward></Response>'

def validate_source(source,state):
    start=source.get('native_xp_start');report=source.get('native_xp_report')
    if start is None:
        if report is not None:raise ValueError('No retrospective XP report')
        return
    validate_start(start)
    create=json.loads(bytes.fromhex(source['create_body_hex']))
    if create['divisionId']!=11-start['division']:raise ValueError('XP division differs from source')
    if report is None:
        if source['status']=='committed':
            from .native_match_forfeit import validate_source as validate_forfeit
            if not validate_forfeit(source,state):raise ValueError('XP source missing completed report')
        return
    required={'version','id','source_id','account_id','persona_id','cycle_id','fixture','status',
              'body_hex','body_sha256','observation','quote','response_xml','profile_before_sha256','profile_after_sha256'}
    if type(report) is not dict or set(report)!=required:raise ValueError('Invalid XP report receipt schema')
    from .difficulty_rewards import source_xp_quote
    body=bytes.fromhex(report['body_hex']);obs=report['observation'];q=source_xp_quote(source,obs['result'])
    if (report['version']!=VERSION or report['id']!=str(uuid.uuid5(uuid.UUID(source['id']),'native-match-xp')) or
        report['source_id']!=source['id'] or report['account_id']!=state['account_id'] or
        report['persona_id']!=state['account_identity']['persona_id'] or report['cycle_id']!=source['cycle_id'] or
        report['fixture']!=source['fixture'] or report['status']!='committed' or
        obs.get('session_id')!=session_id(source['id']) or report['body_sha256']!=sha(body) or
        report['quote']!=q or report['response_xml']!=response(q,source.get('level_reward_start'))):
        raise ValueError('XP report/source/policy mismatch')
    # Reparse durable original bytes as well as checking their checksum.
    import xml.etree.ElementTree as ET
    root=ET.fromstring(body);tag=lambda key:'{'+NS+'}'+key
    own={x.find(tag('Key')).text:int(x.find(tag('Value')).text) for x in root.find(tag('PlayerStats'))}
    other={x.find(tag('Key')).text:int(x.find(tag('Value')).text) for x in root.find(tag('OpponentStats'))}
    score=[own['Goals'],other['Goals']];result='W' if score[0]>score[1] else 'L' if score[0]<score[1] else 'D'
    if (root.tag!=tag('GameReport') or root.find(tag('TerminationReason')).text!='1' or root.find(tag('MatchStartTime')).text!=report_start_time(source) or
        root.find(tag('MatchSessionId')).text!=str(session_id(source['id'])) or
        obs!={'session_id':session_id(source['id']),'score':score,'result':result} or
        own['GoalsAgainst']!=score[1] or other['GoalsAgainst']!=score[0]):
        raise ValueError('XP report contradicts original result')
    if any('MatchDraw' in row for row in (own,other)) and (own.get('MatchDraw'),other.get('MatchDraw'))!=(int(result=='D'),int(result=='D')):
        raise ValueError('XP draw flag contradicts original result')
    for key in ('profile_before_sha256','profile_after_sha256'):
        value=report[key]
        if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('Invalid XP image checksum')
    if source['status']=='committed' and (source['score']!=score or source['result']!=result or source['reward_xp']!=q['xp']):
        raise ValueError('Native End contradicts completed XP report')

def validate(state):
    for source in ([state['active_match']] if state['active_match'] else [])+state['matches']:
        validate_source(source,state)

def validate_intent(before,after,images):
    old=before['active_match'];new=after['active_match']
    if not old or not new or 'native_xp_report' not in new or new==old:return False
    expected=copy.deepcopy(before);expected['prepared']=None
    expected['active_match']['native_xp_report']=new['native_xp_report']
    if (after!=expected or old['status']!='playing' or old.get('native_xp_report') is not None or
        old.get('native_xp_start') is None or len(images)!=1 or images[0]['name']!='profile.json'):
        raise ValueError('XP report intent changes unrelated state')
    validate_source(new,after)
    image=images[0];raw=bytes.fromhex(image['before']);final=bytes.fromhex(image['after']);p=json.loads(raw)
    report=new['native_xp_report'];q=report['quote']
    if (p.get('revival_total_xp',0)!=q['start']['total_xp'] or sha(raw)!=report['profile_before_sha256'] or
        sha(final)!=report['profile_after_sha256']):raise ValueError('XP profile intent checksum/start mismatch')
    p['revival_total_xp']=q['after']['total_xp']
    if json.loads(final)!=p:raise ValueError('XP report changes wallet or unrelated profile')
    return True

def preview(coordinator,state,method,target,headers,body):
    if method!='POST' or target!=REPORT_PATH:return None
    active=state['active_match']
    if active and (active.get('native_match_forfeit') or active.get('native_forfeit_report')):return None
    if active and bool(active.get('atomic_match'))!=coordinator.native_atomic_matches:
        raise ValueError('Cannot change atomic match policy during report')
    candidates=([state['active_match']] if state['active_match'] else [])+state['matches']
    for source in candidates:
        stored=source.get('native_xp_report')
        if stored and stored['body_hex']==body.hex():
            if inspect_report(method,target,headers,body,coordinator,expected_session=session_id(source['id']),expected_start_time=report_start_time(source)) is None:return None
            return {'operation':'xp_report_retry','response_xml':stored['response_xml']}
    source=state['active_match']
    if not source or source['status']!='playing' or not source.get('native_xp_start'):return None
    if source.get('native_xp_report') is not None:raise ValueError('Conflicting completed report retry')
    obs=inspect_report(method,target,headers,body,coordinator,expected_session=session_id(source['id']),expected_start_time=report_start_time(source))
    if obs is None:return None
    start=source['native_xp_start'];profile=load_profile(coordinator.account/'profile.json')
    if (profile.revival_total_xp or 0)!=start['total_xp']:raise ValueError('XP changed during fixture')
    if bool(source.get('difficulty_reward_start')) != coordinator.difficulty_mode(state):
        raise ValueError('Cannot change difficulty rewards during accepted fixture')
    from .difficulty_rewards import source_xp_quote
    q=source_xp_quote(source,obs['result'])
    return {'operation':'xp_report','observation':obs,'quote':q,'response_xml':response(q,source.get('level_reward_start'))}

def accept(coordinator,before,proposal,body):
    if proposal['operation']=='xp_report_retry':return proposal
    after=copy.deepcopy(before);source=after['active_match'];raw=(coordinator.account/'profile.json').read_bytes();p=json.loads(raw)
    p['revival_total_xp']=proposal['quote']['after']['total_xp']
    from .native_season_completion import encode
    final=encode(p)
    source['native_xp_report']={'version':VERSION,'id':str(uuid.uuid5(uuid.UUID(source['id']),'native-match-xp')),
        'source_id':source['id'],'account_id':before['account_id'],'persona_id':before['account_identity']['persona_id'],
        'cycle_id':source['cycle_id'],'fixture':source['fixture'],'status':'committed','body_hex':body.hex(),
        'body_sha256':sha(body),'observation':proposal['observation'],'quote':proposal['quote'],'response_xml':proposal['response_xml'],
        'profile_before_sha256':sha(raw),'profile_after_sha256':sha(final)}
    coordinator._transaction(before,after,[] if coordinator.native_atomic_matches else [coordinator._image('profile.json',final)])
    if coordinator.native_atomic_matches:
        from .native_atomic_match import PRESENTATION
        PRESENTATION[str(coordinator.account)]=source['id']
    return proposal
