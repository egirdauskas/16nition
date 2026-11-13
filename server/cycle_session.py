"""Exact native CycleSession success, preserving the established local token.

Handler02780ea8 ->00310778/002fa5fc ->00310b28 ->002fe218 builds
DTO0034f4a4, decodes00383cac/003504a4 and copies User.SecurityToken
from response+30 to existing context+28. Omission would erase the token.
PresenceId and ShortMessages keep constructor0/empty defaults; no state writes.
"""
from xml.sax.saxutils import escape
from .local_profile import load_profile
from .victory_session import xml_response
PATH='/victory_fwm_s2/Engine.svc/User/CycleSession'
RESPONSE_NS='http://schemas.datacontract.org/2004/07/Victory.TransferObjects'
USER_NS='http://schemas.datacontract.org/2004/07/Victory.AccountManagement.TransferObjects'

def challenge_probe():
    """ACCOMP-001 isolated experiment: announce a ChallengeVersion change.

    Decoded (1452): ShortMessage {Type: ChallengeVersion|QuickEventVersion, Value};
    a changed ChallengeVersion makes 002fe218 raise AccomplishmentDataChanged,
    which posts the stock accomplishment-list request. Only a probe file in a
    reports/.../isolated-account enables it; the follow-up request is captured,
    never answered positively here.
    """
    import json
    from pathlib import Path
    from .local_profile import PROFILE_PATH
    account=PROFILE_PATH.resolve().parent
    root=Path(__file__).resolve().parents[1]
    probe=account/'challenge-version-probe.json'
    if root/'reports' not in account.parents or account.name!='isolated-account' or not probe.is_file():
        return ''
    version=int(json.loads(probe.read_bytes())['challenge_version'])
    return (f'<ShortMessages><ShortMessage><Type>ChallengeVersion</Type>'
            f'<Value>{version}</Value></ShortMessage></ShortMessages>')

def response_for(method,target,headers,body):
    from . import resume_session
    if target == resume_session.PATH:
        return resume_session.response_for(method, target, headers, body)
    profile=load_profile()
    if (method!='GET' or target!=PATH or body
        or headers.get(b'host')!=b'10.0.2.2:18081'
        or headers.get(b'securitytoken')!=profile.victory_security_token.encode()
        or headers.get(b'userid')!=profile.user_id.encode()):
        return None
    from . import local_profile
    from .accomplishments import short_messages
    # ACCOMP-001: a selected account announces its ChallengeVersion (else the isolated probe or nothing).
    messages=short_messages(local_profile.PROFILE_PATH.resolve().parent) or challenge_probe()
    payload=(f'<Response xmlns="{RESPONSE_NS}">{messages}<User xmlns:a="{USER_NS}">'
             f'<a:SecurityToken>{escape(profile.victory_security_token)}</a:SecurityToken>'
             '</User></Response>')
    return xml_response(payload)
