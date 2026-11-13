"""Narrow GetUserInfo candidates supported by parser0102e0f0.

All recognized members have initialized defaults in factory010588fc. The
personaId field is copied to the interface and broadcast by frontend021fd87c.
Only the existing local persona is supplied; no club/player/economy data.
Runtime results are documented in reports/get-user-info.md.
"""
from .identity import json_response
from .local_profile import load_profile

def response_for(method, target, headers, body, candidate, persona_id, football_store=None, preserve_coins=False):
    if not (method == 'GET' and target == '/ut/game/fifaworldmobile/user'
            and headers.get(b'host') == b'10.0.2.2:18081'
            and headers.get(b'x-ut-sid') == b'fifa16-local-sid'
            and headers.get(b'content-length', b'0') == b'0' and body == b''):
        return None
    if candidate == 'empty-object':
        return json_response({})
    if candidate == 'persona' and isinstance(persona_id, int) and persona_id > 0:
        profile=load_profile()
        value={'personaId': persona_id}
        if profile.club_name is not None:value['clubName']=profile.club_name
        if profile.club_abbreviation is not None:value['clubAbbr']=profile.club_abbreviation
        if profile.division_offline is not None:value['divisionOffline']=11-profile.division_offline
        if preserve_coins is True:
            # Captured370 post-match GetUserInfo replaces interface U+0. An
            # omitted collection installs0 and Awards subtracts cached coins.
            # Parser0102e0f0 copies nested+14 (keyAF finalFunds), whereas the
            # separate GetUserCredits parser copies+10 (keyBB funds). Captured
            #378/379 rejects funds-only here: physical UserInfo coins stay0.
            # This is
            # the existing wallet balance, not a positive match award. Points
            # use a different unresolved reader and are not invented here.
            value['currencies']=[{'name':'coins','finalFunds':profile.credits}]
        if football_store is not None:
            state=football_store.load(persona_id)
            from .football_protocol import encode_actives
            if encode_actives(state):value['actives']=encode_actives(state)
        return json_response(value)
    return None
