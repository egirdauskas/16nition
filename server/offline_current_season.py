"""Exact offline SeasonLoadData candidate: explicit no current season.

0230b25c reads seasonId at+3c. Offline0219153c treats -1 as success
and invokes the original new-season selection path. No encoded data emitted.
"""
import json
from pathlib import Path
from .game_auth import SID
from .identity import json_response
PATH = '/ut/game/fifaworldmobile/season/user?type=offline'

def validate_response(value):
    if type(value) is not dict or value != {'seasonId': -1} or type(value.get('seasonId')) is not int:
        raise ValueError('Only explicit no-current-season candidate is justified')
    return value

def response_for(method, target, headers, body, candidate):
    if (method != 'GET' or target != PATH or body or
        headers.get(b'host') != b'10.0.2.2:18081' or
        headers.get(b'x-ut-sid') != SID.encode() or
        headers.get(b'content-length', b'0') != b'0'):
        return None
    return json_response(validate_response(json.loads(Path(candidate).read_text())))
