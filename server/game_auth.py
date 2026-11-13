"""One captured WebSession auth operation; no user/club/game backend.

Evidence: run 28 exact POST and 01022450/01021e7c auth parser/callback.
The SID is an opaque local label. Optional time fields are omitted.
"""
import json
from .identity import json_response

SID = 'fifa16-local-sid'

def response_for(method, target, headers, body):
    if (method != 'POST' or target != '/ut/auth'
        or headers.get(b'host') != b'10.0.2.2:18081'
        or headers.get(b'content-type') != b'application/json'
        or headers.get(b'content-length') != b'1000' or len(body) != 1000):
        return None
    try:
        # Native SessionConnect sends the entire zero-filled 1000-byte buffer.
        request = json.loads(body.rstrip(b'\0'))
    except (ValueError, UnicodeError):
        return None
    if (not isinstance(request, dict) or request.get('sku') != 'FFAWDAND'
        or request.get('method') != 'authcode' or request.get('nucleusPersonaId') != 1
        or type(request.get('identification')) is not dict
        or set(request['identification']) != {'authCode','redirectUrl'}
        or request['identification']['redirectUrl'] != 'nucleus:rest'):
        return None
    from .native_pack_sessions import auth_sid
    sid=auth_sid(request['identification']['authCode'])
    return json_response({'sid':sid}) if sid is not None else None
