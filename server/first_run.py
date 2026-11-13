"""FIRST-001 new-user login branch (stock first-time flow).

Static mapping (8 Nov 2026, libfifa.so, Ghidra base 0x10000):

- Settings success 021fcd94 sends ResetMatch (PUT match/reset).
- Common HTTP handler 01055950 treats 200/204 as success. Any other status is
  mapped by the shared request vtable slot +0x30, 01055948: 465 (0x1d1) -> 1.
- ResetMatch frontend 021fd6c0: result 0 sends GetUserInfo, result 1 sets FUT
  login status 5 (LS_CONNECTED_NEW_USER) through setter 00b57d80, any other
  result sets 6 (LS_FAILED).
- FutLogin.lua onLoggedIn: status 5 -> handleNewUser -> evt_first_time_flow
  {state = "no_favorite_team"} -> ftf.nav Introduction, SelectFavoriteTeam,
  NameYourClub, then the FUT flow with redirectFUT = "ftf".

The branch is selected per account by FIRST_RUN (version first_run_v1, bound
to the account path) and applies only while the profile has neither a club
name nor an abbreviation. Accounts without the selector are unchanged.
"""
import json
import hashlib
from copy import deepcopy
from pathlib import Path

from .local_profile import load_profile

FIRST_RUN = 'first-run.json'
VERSION = 'first_run_v1'
RESET_TARGET = '/ut/game/fifaworldmobile/match/reset'
NEW_USER_STATUS = 465
_SELECTOR_CACHE = {}


def selected(account):
    """The account's validated first-run selector, or None when absent."""
    account = Path(account).resolve()
    path = account / FIRST_RUN
    if not path.exists():
        from .first_run_account import pending_session
        if pending_session(account) is not None:
            return {'version': VERSION, 'account': str(account)}
        return None
    if path.is_symlink():
        raise ValueError('First-run selector alias refused')
    raw = path.read_bytes()
    key = hashlib.sha256(raw).digest()
    if key not in _SELECTOR_CACHE:
        value = json.loads(raw)
        if (type(value) is not dict or set(value) != {'version', 'account'}
                or value['version'] != VERSION):
            raise ValueError('Invalid first-run selector')
        if len(_SELECTOR_CACHE) >= 32:
            _SELECTOR_CACHE.clear()
        _SELECTOR_CACHE[key] = value
    value = deepcopy(_SELECTOR_CACHE[key])
    if value['account'] != str(account):
        raise ValueError('First-run selector bound to another account')
    return value


def select(account):
    """Write the selector for an account (idempotent)."""
    account = Path(account).resolve()
    value = {'version': VERSION, 'account': str(account)}
    data = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    path = account / FIRST_RUN
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('Different first-run selector already present')
        return path
    temporary = path.with_suffix('.json.new')
    temporary.write_bytes(data)
    temporary.replace(path)
    return path


def is_new_user(profile):
    return profile.club_name is None and profile.club_abbreviation is None


def new_user_reply():
    body = b'{}'
    return (b'HTTP/1.1 465 No User\r\nContent-Type: application/json\r\n'
            b'Content-Length: ' + str(len(body)).encode() + b'\r\n'
            b'Connection: close\r\n\r\n' + body)


def reset_response(method, target, headers, body, profile_path):
    """HTTP 465 for the captured ResetMatch of a selected account without a club."""
    if profile_path is None:
        return None
    if not (method == 'PUT' and target == RESET_TARGET
            and headers.get(b'host') == b'10.0.2.2:18081'
            and headers.get(b'x-ut-sid') == b'fifa16-local-sid'
            and headers.get(b'content-length') == b'0' and body == b''):
        return None
    profile_path = Path(profile_path)
    if selected(profile_path.parent) is None:
        return None
    if not is_new_user(load_profile(profile_path)):
        return None
    return new_user_reply()


# --- SetFavTeam (FTF SelectFavoriteTeam) --------------------------------------
# Captured 1528: PUT clientdata/favTeam {"entries":[{"key":0,"value":11}]}.
# Response factory 0230bdc4 (0x28 bytes, vtable 0285ba18); its parser slot
# 01054e60 returns 1 without reading the body, so the common handler's HTTP
# 200 is the whole success contract.

FAV_TEAM_TARGET = '/ut/game/fifaworldmobile/clientdata/favTeam'


def decode_fav_team(method, target, headers, body):
    """The supplied team ID of the captured request, or None."""
    if not (method == 'PUT' and target == FAV_TEAM_TARGET
            and headers.get(b'host') == b'10.0.2.2:18081'
            and headers.get(b'x-ut-sid') == b'fifa16-local-sid'
            and headers.get(b'content-type') == b'application/json'
            and headers.get(b'content-length') == str(len(body)).encode()):
        return None
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        return None
    if type(value) is not dict or set(value) != {'entries'} or type(value['entries']) is not list:
        return None
    if len(value['entries']) != 1:
        return None
    entry = value['entries'][0]
    if (type(entry) is not dict or set(entry) != {'key', 'value'}
            or type(entry['key']) is not int or entry['key'] != 0):
        return None
    team = entry['value']
    if type(team) is not int:
        return None
    from .season_content import eligible_team_ids
    if team not in eligible_team_ids():
        return None
    return team


def fav_team_response(method, target, headers, body, profile_path):
    """Preview: HTTP200 {} for a selected first-run account (no write)."""
    if profile_path is None or selected(Path(profile_path).parent) is None:
        return None
    if decode_fav_team(method, target, headers, body) is None:
        return None
    from .identity import json_response
    return json_response({})


def commit_fav_team(method, target, headers, body, profile_path):
    """Persist the favourite team before the reply; retries rewrite nothing."""
    if fav_team_response(method, target, headers, body, profile_path) is None:
        return None
    from dataclasses import replace
    from .identity import json_response
    from .local_profile import ProfileStore
    team = decode_fav_team(method, target, headers, body)
    from .first_run_account import pending_session, save_favorite_team
    if pending_session(Path(profile_path).parent) is not None:
        save_favorite_team(Path(profile_path).parent, team)
        return json_response({})
    store = ProfileStore(Path(profile_path))
    with store.transaction():
        current = store.load()
        if current.favorite_team_id != team:
            store.save(replace(current, favorite_team_id=team))
    return json_response({})


# --- CreateUser (FTF NameYourClub) --------------------------------------------
# Captured 1529: POST /ut/game/fifaworldmobile/user
#   {"useFut1Data":false,"clubName":"My Club","clubAbbr":"MCB","purchased":false}
# Response factory 022f744c (0x138 bytes, vtable 027eed98), parser 022f7818.
# Members (ordinal table 02884fe8): login (0x10c) -> GetUserInfo parser
# 0102e0f0 at +0x28; bonusPacks (0x41) -> bool +0x118; starterPack (0x1da) ->
# item list via 01028fc0 at +0x11c; userData (0x235) skipped. Callback
# 01a5f9f0 on result 0 installs login through 01a5f75c (the GetUserInfo
# path) and copies bonusPacks to interface+0xf3d0. starterPack is consumed
# only by the frontend delegate (unrecovered jump): not supplied until a
# capture shows its use (FIRST-002).

CREATE_USER_TARGET = '/ut/game/fifaworldmobile/user'


def decode_create_user(method, target, headers, body):
    """(club name, abbreviation) of the captured CreateUser request, or None."""
    if not (method == 'POST' and target == CREATE_USER_TARGET
            and headers.get(b'host') == b'10.0.2.2:18081'
            and headers.get(b'x-ut-sid') == b'fifa16-local-sid'
            and headers.get(b'content-type') == b'application/json'
            and headers.get(b'content-length') == str(len(body)).encode()):
        return None
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        return None
    if type(value) is not dict or set(value) != {'useFut1Data', 'clubName', 'clubAbbr', 'purchased'}:
        return None
    if value['useFut1Data'] is not False or value['purchased'] is not False:
        return None
    name = value['clubName']
    abbreviation = value['clubAbbr']
    # Same bounds as the captured ChangeClubName (original edit popup 5-15/3).
    if (type(name) is not str or not name.isascii() or not 5 <= len(name) <= 15
            or name != name.strip() or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        return None
    if (type(abbreviation) is not str or not abbreviation.isascii() or len(abbreviation) != 3
            or abbreviation != abbreviation.strip().upper()
            or any(ord(c) < 32 or ord(c) == 127 for c in abbreviation)):
        return None
    return name, abbreviation


def create_user_reply(profile):
    from .identity import json_response
    login = {'personaId': profile.persona_id, 'clubName': profile.club_name,
             'clubAbbr': profile.club_abbreviation}
    return json_response({'login': login, 'bonusPacks': False})


def _create_user_target(method, target, headers, body, profile_path):
    if profile_path is None or selected(Path(profile_path).parent) is None:
        return None
    return decode_create_user(method, target, headers, body)


def create_user_response(method, target, headers, body, profile_path):
    """Preview without writing: new user, or an exact retry of the stored club."""
    from dataclasses import replace
    club = _create_user_target(method, target, headers, body, profile_path)
    if club is None:
        return None
    profile = load_profile(Path(profile_path))
    if not is_new_user(profile) and (profile.club_name, profile.club_abbreviation) != club:
        return None
    if is_new_user(profile) and profile.favorite_team_id is None:
        return None
    return create_user_reply(replace(profile, club_name=club[0], club_abbreviation=club[1]))


def commit_create_user(method, target, headers, body, profile_path):
    """Persist club name and abbreviation together, once; retries rewrite nothing."""
    from dataclasses import replace
    from .local_profile import ProfileStore
    club = _create_user_target(method, target, headers, body, profile_path)
    if club is None:
        return None
    from .first_run_account import pending_session, create_account
    account = Path(profile_path).parent
    pending = pending_session(account)
    if pending is not None:
        if pending.get('favorite_team_id') is None:
            return None
        # Reuse Claude's physically proven request/reply, with all starter
        # ownership, wallet and packs published by one new-account operation.
        create_account(account, club[0], club[1], creation_id=pending['creation_id'])
        return create_user_reply(load_profile(profile_path))
    from . import first_run_starter
    store = ProfileStore(Path(profile_path))
    with store.transaction():
        current = store.load()
        if is_new_user(current):
            if current.favorite_team_id is None:
                return None
            # FIRST-002 starter club first: a crash before the profile write
            # leaves a new user whose retry finds the same receipt.
            first_run_starter.grant(Path(profile_path).parent, current.favorite_team_id)
            current = replace(current, club_name=club[0], club_abbreviation=club[1])
            store.save(current)
        elif (current.club_name, current.club_abbreviation) != club:
            return None
    return create_user_reply(current)


def preview(method, target, headers, body, profile_path):
    """First-run replies without writes (favourite team, club creation)."""
    reply = fav_team_response(method, target, headers, body, profile_path)
    if reply is not None:
        return reply
    return create_user_response(method, target, headers, body, profile_path)


def commit_request(method, target, headers, body, profile_path):
    """First-run commits (favourite team, club creation) or None."""
    reply = commit_fav_team(method, target, headers, body, profile_path)
    if reply is not None:
        return reply
    return commit_create_user(method, target, headers, body, profile_path)
