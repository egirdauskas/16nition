"""Explicit opt-in named squad operations through the existing FootballStore.

Create POST was captured884; SaveSquad mode1 suppresses the /id suffix and
shares factory0103c474/parser0103cbdc. Its returned numeric id binds the created
squad. Unknown management operations remain unsupported until captured.
"""
from dataclasses import replace
import json
import re
from pathlib import Path
from .account_transaction import ACCOUNT_LOCK
from .game_auth import SID
from .identity import json_response
from .local_football import validate
from . import local_squads

BASE = '/ut/game/fifaworldmobile/squad'
DELETE_BASE = '/ut/delete/game/fifaworldmobile/squad'
ACCOUNT = None
RELEASE_SHA = None


def configure(account=None):
    global ACCOUNT, RELEASE_SHA
    ACCOUNT = Path(account).resolve() if account is not None else None
    RELEASE_SHA = None
    from .squad_slot_authority import configure as configure_authority
    configure_authority(ACCOUNT)
    if ACCOUNT is not None:
        from .squad_management_release import MARKER, validate, sha
        if (ACCOUNT/MARKER).exists():
            validate(ACCOUNT)
            RELEASE_SHA = sha(ACCOUNT/MARKER)


def selected(store):
    if ACCOUNT is None or store.path.resolve() != ACCOUNT/'football.json': return False
    if RELEASE_SHA is not None:
        from .squad_management_release import MARKER, sha
        if sha(ACCOUNT/MARKER) != RELEASE_SHA: raise ValueError('Squad admission changed during runtime')
    return True


def proposal(method, target, headers, body, store, state):
    if not selected(store): return None
    deletion = re.fullmatch(re.escape(DELETE_BASE)+r'/(0|[1-9][0-9]*)', target)
    if method == 'GET' and deletion:
        if (body or headers.get(b'host') != b'10.0.2.2:18081' or
                headers.get(b'x-ut-sid') != SID.encode() or
                headers.get(b'content-length', b'0') != b'0'):
            return None
        from .squad_slot_authority import session_id
        authority=session_id(store,headers)
        nid = int(deletion[1]); record = local_squads.by_native_id(state, nid)
        # No operation nonce: never let an old delete remove a replacement.
        if record is not None and nid in state.retired_native_squad_ids and authority is None:
            raise ValueError('Ambiguous deletion of a reused native squad ID')
        if record is None:
            if nid not in state.retired_native_squad_ids: raise ValueError('Unknown native squad deletion')
            after = state
        else:
            after = local_squads.delete(state, record.id)
        validate(after, store.catalog)
        # 892 route0xc/selector5, factory0230d804 initializes the common
        # response; parser0230d8c0 reads no operation-specific JSON members.
        return after, {}
    match = re.fullmatch(re.escape(BASE)+r'/(0|[1-9][0-9]*)', target)
    creation = method == 'POST' and target == BASE
    if not creation and not (method == 'PUT' and match): return None
    if (headers.get(b'host') != b'10.0.2.2:18081' or headers.get(b'x-ut-sid') != SID.encode() or
            headers.get(b'content-type') != b'application/json' or
            headers.get(b'content-length', str(len(body)).encode()) != str(len(body)).encode()):
        return None
    from .squad_slot_authority import session_id
    authority=session_id(store,headers)
    value = json.loads(body)
    if type(value) is not dict:return None
    if not creation and 'players' not in value:
        from .save_squad import validate_roles
        nid=int(match[1]); record=local_squads.by_native_id(state,nid)
        if record is None or not validate_roles(value,state,record.id,wire_squad_id=nid):return None
        return state, {'id':nid} if nid else {}
    if 'players' not in value:return None
    from .squad_mutation import decode
    sid = value.get('id') if creation else int(match[1])
    update = decode(body, state, squad_id=sid, create=creation, management=True)
    if creation:
        after, sid = local_squads.create(state, update, body,session_id=authority)
        # 890 original CopySquad makes the newly returned ID current, without
        # a subsequent GetById. Select only on first creation: a stale retry
        # must not change a later user selection or roll back a filled team.
        if after != state:
            after = local_squads.select(after, sid)
        reply_id = local_squads.wire_id(local_squads.get(after, sid))
    else:
        record = local_squads.by_native_id(state, sid)
        if record is None: raise ValueError('Unknown squad update')
        reply_id = sid; sid = record.id
        name = update.name or record.name
        if name and any(r.id != sid and r.name == name for r in local_squads.records(state)):
            raise ValueError('Squad name already exists')
        # Normal SaveCurrentSquad sends an empty name even for a named team
        # (895). Preserve its name, but accept the newly calculated summary.
        summary=update.summary
        record = replace(record, name=name, lineup=update.lineup, formation_id=update.formation_id,
                         manager_id=update.manager_id, summary=summary)
        after = local_squads.put(state, record)
    validate(after, store.catalog)
    return after, {'id': reply_id} if creation or reply_id != 0 else {}


def response_for(method, target, headers, body, store):
    try:
        found = proposal(method, target, headers, body, store, store.load(1))
        return json_response(found[1]) if found is not None else None
    except (ValueError, TypeError, KeyError, UnicodeError):
        return None


def commit_request(method, target, headers, body, store):
    with ACCOUNT_LOCK, store.transaction():
        before = store.load(1)
        found = proposal(method, target, headers, body, store, before)
        if found is None: return None
        after, response = found
        if after != before: store.save(after)
        return json_response(response)


def commit_loaded_squad(method,target,headers,body,store):
    """Persist the original client's successful LoadSquadById selection.

    888's Build/load/return makes alpha the native current squad (green tick),
    with GET /squad/1 and no separate activation write. This local compatibility
    policy keeps startup's ActiveSquad aligned with that observed selection.
    The wire response still contains only the requested owned squad.
    """
    if not selected(store) or method!='GET' or body:return None
    match=re.fullmatch(re.escape(BASE)+r'/(0|[1-9][0-9]*)',target)
    if (not match or headers.get(b'host')!=b'10.0.2.2:18081' or
        headers.get(b'x-ut-sid')!=SID.encode() or headers.get(b'content-length',b'0')!=b'0'):return None
    native_id=int(match[1])
    with ACCOUNT_LOCK,store.transaction():
        before=store.load(1)
        record=local_squads.by_native_id(before,native_id)
        if record is None:return None
        sid=record.id
        after=local_squads.select(before,sid);validate(after,store.catalog)
        if after!=before:
            store.save(after)
            return {'id':sid,'native_id':native_id,'previous_id':before.squad_id,'policy':'native_loaded_squad_selection_v1'}
    return None
