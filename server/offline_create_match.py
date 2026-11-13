"""Scoped CreateMatch adapter for the captured offline request.

010335cc recognizes startDateTime (signed64 response+28) and optional squad.
00b57044 always copies the scalar into frontend match context+48. The factory
does not initialize it. Omit squad to preserve the proven installed roster.
No match ID, result handling or persistent match store is introduced.
"""
import json
import time
from pathlib import Path
from .game_auth import SID
from .identity import json_response

PATH='/ut/game/fifaworldmobile/match'
REQUEST={'squadId':0,'type':'OFFLINE','customData1':0}

def validate_response(value):
    if (type(value) is not dict or set(value)!={'startDateTime'}
        or type(value['startDateTime']) is not int
        or not 0<=value['startDateTime']<2**63):
        raise ValueError('CreateMatch requires one explicit nonnegative signed64 startDateTime')
    return value

def response_for(method,target,headers,body,candidate,season_store=None,football_store=None):
    if (method!='POST' or target!=PATH or
        headers.get(b'host')!=b'10.0.2.2:18081' or
        headers.get(b'x-ut-sid')!=SID.encode() or
        headers.get(b'content-type')!=b'application/json'):
        return None
    try:
        if b'content-length' in headers and int(headers[b'content-length'])!=len(body):return None
        value=json.loads(body)
        if type(value) is not dict:return None
        fields=set(value)
        if fields not in (set(REQUEST),set(REQUEST)|{'seasonId','divisionId'}):return None
        expected_request=dict(REQUEST)
        if football_store is not None:
            from .squad_management import selected
            if selected(football_store):
                from .local_squads import active_record,wire_id
                expected_request['squadId']=wire_id(active_record(football_store.load(1)))
        if (any(value.get(key)!=expected for key,expected in expected_request.items()) or
            type(value.get('squadId')) is not int or
            type(value.get('customData1')) is not int):
            return None
        if 'seasonId' in value:
            #0103323c conditionally emits these fields for positive divisions.
            #The user's Division10 wire request is1/1; authorize only the
            #currently persisted local season, with the proven11-index map.
            if season_store is None:return None
            current=season_store.load()
            if (current is None or type(value['seasonId']) is not int or
                type(value['divisionId']) is not int or
                value['seasonId']!=current.season_id or
                value['divisionId']!=11-current.division_index):return None
        response={'startDateTime':int(time.time())} if candidate=='clock' else json.loads(Path(candidate).read_text())
        return json_response(validate_response(response))
    except (ValueError,UnicodeError):
        return None
