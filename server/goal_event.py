"""Only stock ScoreAGoal ReportEvent transport completion, without progression.

Live handler02781358 validates XML through00310778/002fa5fc, then invokes
00310f94 (bx lr). There is no operation DTO or payload consumer.
"""
import xml.etree.ElementTree as ET
from .local_profile import load_profile
from .victory_session import xml_response

PATH = '/victory_fwm_s2/Engine.svc/Challenge/ReportEvent'
NS = 'http://schemas.datacontract.org/2004/07/Victory.Challenge.TransferObjects'
PAYLOAD = b'<Response xmlns="http://schemas.datacontract.org/2004/07/Victory.Service"/>'
PARAMS = frozenset(('ScoreGoalTimeSecond', 'IsMatchInvite', 'PlayerId',
                   'GoalSituation', 'TeamId', 'ShotType', 'ShotDistanceYard',
                   'ScoreHalf', 'PlayerTeamId', 'PlayerLeagueId',
                   'PlayerCountryId', 'PlayerFUTItemId'))
SIM_PARAMS = frozenset(('PlayerTeamId','PlayerLeagueId','PlayerCountryId',
                       'ScoreGoalTimeSecond','PlayerId','TeamId','ScoreHalf'))

def response_for(method, target, headers, body, *, match_session_id=None):
    profile = load_profile()
    if (method != 'POST' or target != PATH
        or headers.get(b'host') != b'10.0.2.2:18081'
        or headers.get(b'securitytoken') != profile.victory_security_token.encode()
        or headers.get(b'userid') != profile.user_id.encode()
        or headers.get(b'content-type') != b'text/xml;charset=utf-8'
        or not body or len(body) > 8192):
        return None
    try:
        if int(headers.get(b'content-length', b'-1')) != len(body):
            return None
        # Only the observed stock request family, not a general Challenge API.
        if b'<!' in body:
            return None
        root = ET.fromstring(body)
        tag = lambda key: '{'+NS+'}'+key
        if root.tag != tag('ReportEventParams') or [x.tag for x in root] != [tag('EventList')]:
            return None
        events = list(root[0])
        if len(events) != 1 or events[0].tag != tag('Event'):
            return None
        event = events[0]
        if [x.tag for x in event] != [tag('EventType'), tag('ParamList')]:
            return None
        if event[0].text == 'ScoreOwnGoal':
            #1370 genuine played tournament own goal: empty ParamList only.
            #Same ReportEvent handler02781358 (XML validation, then bx lr); the
            #ack is event-type independent. Unacknowledged it shows CONNECTION LOST.
            if list(event[0]) or list(event[1]) or (event[1].text or '').strip():return None
            return xml_response(PAYLOAD)
        if event[0].text != 'ScoreAGoal':
            return None
        keys = [];values={}
        for param in event[1]:
            if param.tag != tag('EventParam') or [x.tag for x in param] != [tag('ParamType'), tag('ParamValue')]:
                return None
            if list(param[0]) or list(param[1]) or not param[1].text:
                return None
            keys.append(param[0].text)
            values[param[0].text]=param[1].text
        # Genuine368 native simulation reports exactly these seven fields.
        # Same ScoreAGoal DTO/fieldless consumer; no XP or result installation.
        allowed=frozenset(keys) in (PARAMS,SIM_PARAMS)
        #784 captures the Sim variant;859 captures the full played variant
        #after a genuine penalty goal. Both add the installed source MatchId.
        #Same fieldless callback00310f94; no reward/result effect.
        if (not allowed and type(match_session_id) is int and 0<match_session_id<=0x7fffffffffffffff
            and frozenset(keys) in (SIM_PARAMS|{'MatchId'},PARAMS|{'MatchId'}) and
            values.get('MatchId')==str(match_session_id)):
            allowed=True
        if len(keys)!=len(set(keys)) or not allowed:
            return None
        # CLUB-005: remember the scorer until the match commits (display stats only).
        from .local_profile import PROFILE_PATH
        from .item_history import record_goal
        record_goal(PROFILE_PATH.parent, body, values)
        # ACCOMP-001: the same event counts toward challenges once its match commits.
        from .accomplishments import record_goal as record_accomplishment_goal
        record_accomplishment_goal(PROFILE_PATH.parent, body, values)
        return xml_response(PAYLOAD)
    except (ValueError, TypeError, ET.ParseError):
        return None
