"""Captured ChangeClubName51; status-only parser022f6464, gated local profile edit."""
from dataclasses import replace
import json
from .account_transaction import account_locked
from .identity import json_response
from .local_profile import ProfileStore

PATH='/ut/game/fifaworldmobile/user/club'


def decode(method,target,headers,body):
    from .game_auth import SID
    if (method!='PUT' or target!=PATH or headers.get(b'host')!=b'10.0.2.2:18081' or
            headers.get(b'x-ut-sid')!=SID.encode() or headers.get(b'content-type')!=b'application/json' or
            headers.get(b'content-length')!=str(len(body)).encode()):
        raise ValueError('Not the authenticated captured ChangeClubName request')
    value=json.loads(body)
    if type(value) is not dict or set(value)!={'clubName','clubAbbr'}:
        raise ValueError('Unmapped club name envelope')
    name,abbr=value['clubName'],value['clubAbbr']
    # Original EditAcronymPopup displays5–15/3, trims and uppercases abbreviation.
    if (type(name) is not str or not name.isascii() or not 5<=len(name)<=15 or name!=name.strip() or
            any(ord(c)<32 or ord(c)==127 for c in name) or type(abbr) is not str or
            not abbr.isascii() or len(abbr)!=3 or abbr!=abbr.strip().upper() or
            not abbr.strip() or any(ord(c)<32 or ord(c)==127 for c in abbr)):
        raise ValueError('Invalid original club name/abbreviation bounds')
    return name,abbr


def proposal(method,target,headers,body,store):
    from .club_item_actions import rename_enabled
    if not rename_enabled(store):return None
    name,abbr=decode(method,target,headers,body)
    account=store.path.parent
    for journal in ('native-seasons.json','packs.json','purchases.json','quick-sells.json','free-coins.json','free-packs.json'):
        p=account/journal
        if p.exists() and json.loads(p.read_bytes()).get('prepared'):
            raise ValueError('Recover pending transaction before club rename')
    profile=ProfileStore(account/'profile.json')
    return profile,replace(profile.load(),club_name=name,club_abbreviation=abbr)


@account_locked
def response_for(method,target,headers,body,store):
    try:
        if proposal(method,target,headers,body,store) is None:return None
    except (ValueError,TypeError,KeyError,UnicodeError):return None
    # Derived response factory022f61e8 adds no fields; parser022f6464 returns1.
    return json_response({})


@account_locked
def commit_request(method,target,headers,body,store):
    result=proposal(method,target,headers,body,store)
    if result is None:return None
    profile,expected=result
    with profile.transaction():
        # Re-read inside the existing profile lock; no balance/XP stale copy.
        name,abbr=decode(method,target,headers,body)
        current=profile.load();expected=replace(current,club_name=name,club_abbreviation=abbr)
        if expected!=current:profile.save(expected)
    return json_response({})
