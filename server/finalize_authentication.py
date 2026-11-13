"""Only the captured native FOS finalization operation.

00310778/002fa5fc require a nonempty namespace-prefixed XML buffer. FOS
success00310d18 ignores its payload; no account/session fields are generated.
Activation stays opt-in until runtime continuation is verified.
"""
from urllib.parse import urlsplit, parse_qs
from .local_profile import load_profile
from .victory_session import xml_response

PATH = '/victory_fwm_s2/Engine.svc/User/FinalizeAuthentication'
PAYLOAD = b'<Response xmlns="http://schemas.datacontract.org/2004/07/Victory.Service"/>'

QUEUE_PREREQUISITES = {
    '/victory_fwm_s2/Engine.svc/User/PrivacySettings',
    '/victory_fwm_s2/Engine.svc/QuickEvent/GetEvents',
    '/victory_fwm_s2/Engine.svc/QuickEvent/GetProgression',
}

def queue_response_for(method, target, headers, body):
    """Run99/100 transport gates only; false flags/empty initialized vector.

    Privacy:003133c4/0031697c. The two captured QuickEvent operations
    use0033d1e4/0033eb60 and0033ddd4/0034401c: empty vectors and an
    initialized empty version string. Runs101/102 capture GetProgression
    occupying the sole transport slot ahead of FOS/message work.
    No members are supplied and no account or event records are generated.
    """
    profile = load_profile()
    if (method != 'GET' or target not in QUEUE_PREREQUISITES or body
        or headers.get(b'host') != b'10.0.2.2:18081'
        or headers.get(b'securitytoken') != profile.victory_security_token.encode()
        or headers.get(b'userid') != profile.user_id.encode()):
        return None
    return xml_response(PAYLOAD)

def response_for(method, target, headers, body):
    url = urlsplit(target)
    profile = load_profile()
    if (method != 'PUT' or url.path != PATH or body
        or parse_qs(url.query) != {'remotePersonaId':[str(profile.persona_id)], 'errorCode':['0']}
        or headers.get(b'host') != b'10.0.2.2:18081'
        or headers.get(b'securitytoken') != profile.victory_security_token.encode()
        or headers.get(b'userid') != profile.user_id.encode()):
        return None
    from .welcome_gift import note
    note('finalize')
    return xml_response(PAYLOAD)
