"""Isolated, source-bound OfflineMatchInfo candidate; no rewards or results.

Stock Sim sends event151 after PlaySim (0219de34 ->009559f0 ->0030e104).
Response0032a200 reads MatchSessionId, then00301b74 installs VictoryClient+a0/a4.
Names and envelope are recovered from0033317c. Positive consumption is still
experiment-gated. Session IDs are local server identities derived from the
already durable fixture UUID, never client-generated match results.
"""
import uuid
import xml.etree.ElementTree as ET
from .local_profile import load_profile
from .victory_session import xml_response

TARGET='/victory_fwm_s2/Engine.svc/matchflow/offlineMatch?eventId=151&isFirstTimeFlow=False'
PLAYED_TARGET=TARGET.replace('eventId=151','eventId=51')
NS='http://schemas.datacontract.org/2004/07/Victory.MatchFlow.TransferObjects'
REPORT_PATH='/victory_fwm_s2/Engine.svc/matchflow/report'

def inspect_report(method,target,headers,body,coordinator,*,expected_session=None,expected_start_time=None,allow_forfeit=False):
    """Captured786 normal Sim GameReport only; never synthesize a result."""
    if method!='POST' or target!=REPORT_PATH:return None
    p=load_profile(coordinator.account/'profile.json')
    if (headers.get(b'host')!=b'10.0.2.2:18081' or
        headers.get(b'securitytoken')!=p.victory_security_token.encode() or
        headers.get(b'userid')!=p.user_id.encode() or
        headers.get(b'content-type')!=b'text/xml;charset=utf-8' or
        headers.get(b'content-length')!=str(len(body)).encode() or
        not body or len(body)>16384 or b'<!' in body):return None
    tag=lambda name:'{'+NS+'}'+name
    try:
        root=ET.fromstring(body)
        names=['MatchSessionId','TerminationReason','PlayerStats','OpponentStats','MatchStartTime','OpponentNucleusPersonaId']
        if root.tag!=tag('GameReport') or [n.tag for n in root]!=[tag(n) for n in names]:return None
        if expected_start_time is None:
            from .native_played_protocol import report_start_time
            with coordinator.locked():active=coordinator._load()['active_match']
            expected_start_time=report_start_time(active) if active else '-1'
        reason=root[1].text
        if reason not in (('1','3') if allow_forfeit else ('1',)) or root[4].text!=expected_start_time or root[5].text!='0':return None
        sid=active_session_id(coordinator) if expected_session is None else expected_session
        if sid is None or root[0].text!=str(sid):return None
        stats=[]
        known={'Goals','GoalsAgainst','ShotsOnTarget','SuccessfulTackles','Corners','Fouls',
               'YellowCards','RedCards','Offsides','PassingPercentage','PossessionPercentage',
               'ManOfTheMatch','CleanSheets','MatchWon','MatchLost','MatchDraw'}
        for section in root[2:4]:
            row={}
            for item in section:
                if item.tag!=tag('MatchStat') or [n.tag for n in item]!=[tag('Key'),tag('Value')]:return None
                key=item[0].text;value=item[1].text
                if key not in known or key in row or not value or not value.isascii() or not value.isdecimal():return None
                number=int(value)
                if str(number)!=value or number>0x7fffffff:return None
                row[key]=number
            if not {'Goals','GoalsAgainst'}<=row.keys():return None
            stats.append(row)
        own,other=stats;score=[own['Goals'],other['Goals']]
        if own['GoalsAgainst']!=score[1] or other['GoalsAgainst']!=score[0]:return None
        if any(v>99 for v in score):return None
        result='W' if score[0]>score[1] else 'L' if score[0]<score[1] else 'D'
        if (own.get('MatchWon',0),own.get('MatchLost',0),other.get('MatchWon',0),other.get('MatchLost',0))!=(int(result=='W'),int(result=='L'),int(result=='L'),int(result=='W')):return None
        #805's genuine0-0 report uses MatchDraw1 on both sides. It is a
        #result flag, not another XP/coin award or a different report endpoint.
        if any('MatchDraw' in row for row in stats) and (own.get('MatchDraw'),other.get('MatchDraw'))!=(int(result=='D'),int(result=='D')):return None
        observed={'session_id':sid,'score':score,'result':result}
        if reason=='3':observed['termination_reason']=3
        return observed
    except (ET.ParseError,ValueError,TypeError):return None

def report_response_for(method,target,headers,body,coordinator):
    if inspect_report(method,target,headers,body,coordinator) is None:return None
    #00328a44 initializes every omitted member.00300fa0 then emits original
    #SummaryInfo/StatAwards and a fresh UserPlate request. No grant or profile
    #mutation in this transport-only control. Positive XP is not enabled here.
    return xml_response(f'<Response xmlns="{NS}"/>')

def session_id(source_id):
    # One deterministic positive signed64 identity; refuse collisions rather
    # than introduce another allocator or mutate historical fixture receipts.
    return (uuid.UUID(source_id).int & 0x7fffffffffffffff) or 1

def _source_session_id(state, *, early_played=False):
    if state['prepared'] is not None:raise ValueError('Recover journal before assigning session')
    active=state['active_match']
    if not active:return None
    if active['status']!='playing':
        # Original910 sends event51 concurrently with FUT Play. Accepted Create
        # already owns this stable identity. Projecting it grants nothing and
        # must not relax GameReport's requirement for accepted Play.
        if not (early_played and active['status']=='created' and active.get('played_match')):return None
    sid=session_id(active['id'])
    if any(session_id(m['id'])==sid for m in state['matches']):
        raise ValueError('Local match session identity collision')
    return sid

def active_session_id(coordinator):
    with coordinator.locked():return _source_session_id(coordinator._load())

def response_for(method,target,headers,body,coordinator):
    if method!='GET' or target not in (TARGET,PLAYED_TARGET) or body:return None
    with coordinator.locked():
        state=coordinator._load();active=state['active_match']
        played=bool(active and active.get('played_match'))
        if played and not (coordinator.native_played_matches or coordinator.native_mixed_matches):return None
        expected=PLAYED_TARGET if played else TARGET
        if target!=expected:return None
        profile=load_profile(coordinator.account/'profile.json')
        if (headers.get(b'host')!=b'10.0.2.2:18081' or
            headers.get(b'securitytoken')!=profile.victory_security_token.encode() or
            headers.get(b'userid')!=profile.user_id.encode()):return None
        sid=_source_session_id(state,early_played=played)
        if sid is None:return None
        return xml_response(f'<OfflineMatchInfo xmlns="{NS}"><MatchSessionId>{sid}</MatchSessionId></OfflineMatchInfo>')
