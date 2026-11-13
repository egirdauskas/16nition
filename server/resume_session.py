"""Original Victory resume ACK; no identity, wallet or reward mutation.

003058d4 builds operation2c via00356c2c and CallbackResponseTemplate00310854.
Common XML validation00310778 dispatches003108fc through closure00306c14 to
00303fdc. That callback ignores the response payload, clears client+108 and
optional transport+28, and leaves the current native session/token intact.
"""
from .local_profile import load_profile
from .victory_session import xml_response

PATH = '/victory_fwm_s2/Engine.svc/User/ResumeSession'
PAYLOAD = b'<Response xmlns="http://schemas.datacontract.org/2004/07/Victory.Service"/>'


def response_for(method, target, headers, body):
    if (method != 'PUT' or target != PATH or body
            or headers.get(b'host') != b'10.0.2.2:18081'
            or headers.get(b'content-length', b'0') != b'0'
            or headers.get(b'content-type', b'').split(b';', 1)[0] != b'text/xml'
            or not headers.get(b'deviceid', b'').isdigit()):
        return None
    profile = load_profile()
    if (headers.get(b'securitytoken') != profile.victory_security_token.encode()
            or headers.get(b'userid') != profile.user_id.encode()):
        return None
    return xml_response(PAYLOAD)
