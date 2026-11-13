"""Only the captured native GetPersonaAccomplishments empty-collection reply.

Live handler02781178 ->00310778/002fa5fc ->00310e60 (tail preserves
buffer/length) ->003034c0 ->00383b6c/00320188. An empty XML root has no
child records, leaving the initialized vector empty. No accomplishments,
rewards or persistent progress are generated. Activation is explicit.

ACCOMP-001 isolated probes (below) serve fixed XML files that exist only in a
reports/.../isolated-account; they grant and record nothing.
"""
from pathlib import Path

from . import local_profile
from .local_profile import load_profile
from .victory_session import xml_response

PATH = '/victory_fwm_s2/Engine.svc/Challenge/GetPersonaAccomplishments'
PAYLOAD = b'<Response xmlns="http://schemas.datacontract.org/2004/07/Victory.Service"/>'

CHALLENGES = '/victory_fwm_s2/Engine.svc/Challenge/GetChallenges'
DETAILS = '/victory_fwm_s2/Engine.svc/Challenge/GetDetails'
REWARDS_TO_CLAIM = '/victory_fwm_s2/Engine.svc/Challenge/GetRewardsToClaim'
LOCALIZATION = '/loc/en_us/Challenges.xml'

# (method, target) -> (probe file, session headers required, body check).
# Genuine requests: GetChallenges 1453 (GET, no body); GetDetails 1480 (POST
# LongList of ChallengeIds; reply = root of Challenge elements, decoders
# 00303ff4 -> 00383c0c -> 0031db84 -> 0031dbd0); localization 1485 (plain
# ProtoHttp GET once user.ini sets ONLINE/CHALLENGE_PATH_LOC_TEXT, downloader
# slot 0 at 00a95318); GetRewardsToClaim 1488 (GET, no body; reply root fields
# decoded by 0031ae8c -> 0031aed8, handler 00303930).
PROBES = {
    ('GET', CHALLENGES): ('challenges-probe.xml', True, lambda body: not body),
    ('POST', DETAILS): ('details-probe.xml', True, lambda body: body.startswith(b'<LongList ')),
    ('GET', LOCALIZATION): ('challenge-loc-probe.xml', False, lambda body: not body),
    ('GET', REWARDS_TO_CLAIM): ('rewards-probe.xml', True, lambda body: not body),
}


def _isolated_account():
    # Read at call time: local_profile rebinds PROFILE_PATH for lab runtimes.
    account = local_profile.PROFILE_PATH.resolve().parent
    root = Path(__file__).resolve().parents[1]
    if root / 'reports' not in account.parents or account.name != 'isolated-account':
        return None
    return account


def _session_ok(headers, profile):
    return (headers.get(b'host') == b'10.0.2.2:18081'
            and headers.get(b'securitytoken') == profile.victory_security_token.encode()
            and headers.get(b'userid') == profile.user_id.encode())


def isolated_probe(method, target, headers, body):
    """Serve a fixed probe file for one captured request, isolated account only."""
    entry = PROBES.get((method, target))
    account = _isolated_account()
    if entry is None or account is None:
        return None
    name, needs_session, body_ok = entry
    probe = account / name
    if not probe.is_file() or not body_ok(body):
        return None
    if needs_session and not _session_ok(headers, load_profile()):
        return None
    if not needs_session and headers.get(b'host') != b'10.0.2.2:18081':
        return None
    return xml_response(probe.read_bytes())


def progress_probe():
    """Fixed GetPersonaAccomplishments records (display only), isolated account only."""
    account = _isolated_account()
    if account is None or not (account / 'accomplishments-probe.xml').is_file():
        return None
    return xml_response((account / 'accomplishments-probe.xml').read_bytes())


def response_for(method, target, headers, body):
    # ACCOMP-001: an account that selected the feature gets the real replies.
    from . import accomplishments
    selected = accomplishments.response_for(method, target, headers, body)
    if selected is not None:
        return selected
    probe = isolated_probe(method, target, headers, body)
    if probe is not None:
        return probe
    profile = load_profile()
    if (method != 'GET' or target != PATH + '?remotePersonaId=' + str(profile.persona_id)
            or body or not _session_ok(headers, profile)):
        return None
    probe = progress_probe()
    if probe is not None:
        return probe
    return xml_response(PAYLOAD)
