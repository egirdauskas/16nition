"""Named squad references in the existing FootballStore atomic document.

The active lineup remains its canonical legacy projection. Inactive squads
reference the same owned instances; they never allocate or duplicate players.
"""
from dataclasses import dataclass, replace, asdict
import hashlib
from .local_football import SquadSlot, SquadSummary, validate_squad_name
from .local_formations import validate_formation


@dataclass(frozen=True)
class SquadRecord:
    id: int
    name: str
    lineup: tuple
    formation_id: int | None
    manager_id: int = 0
    summary: SquadSummary | None = None
    native_id: int | None = None


@dataclass(frozen=True)
class SquadCreation:
    body_sha256: str
    squad_id: int
    request_id: int


def decode_record(value):
    return SquadRecord(value['id'], value['name'], tuple(SquadSlot(**v) for v in value['lineup']),
                       value['formation_id'], value.get('manager_id', 0),
                       SquadSummary(**value['summary']) if value.get('summary') is not None else None,
                       value.get('native_id'))


def active_record(state):
    manager = state.squad_manager_id
    if manager is None:
        manager = state.active_manager.instance_id if state.active_manager else 0
    return SquadRecord(state.squad_id, state.squad_name, state.active_lineup,
                       state.formation_id, manager, state.squad_summary, state.squad_native_id)


def wire_id(record):
    return record.id if record.native_id is None else record.native_id


def native_records(state):
    return tuple(sorted(records(state), key=wire_id))


def by_native_id(state, native_id):
    return next((r for r in records(state) if wire_id(r) == native_id), None)


def records(state):
    return tuple(sorted((active_record(state), *state.other_squads), key=lambda r: r.id))


def get(state, squad_id):
    return next((r for r in records(state) if r.id == squad_id), None)


def validate_bank(state):
    ids = set(); native_ids = set(); names = set(); owned = {i.instance_id for i in state.owned_items}
    manager = state.active_manager.instance_id if state.active_manager else 0
    managers = {0, manager} | {m.instance_id for m in state.owned_managers}
    trade = {i.instance_id for i in state.inventory_locations if i.pile == 'trade'}
    if any(type(r) is not SquadRecord for r in state.other_squads):
        raise ValueError('Invalid saved squad record')
    for r in records(state):
        if type(r.id) is not int or not 0 <= r.id < 0x7fffffff or r.id in ids:
            raise ValueError('Invalid or duplicate squad identity')
        ids.add(r.id); validate_squad_name(r.name)
        nid = wire_id(r)
        if type(nid) is not int or not 0 <= nid < 0x7fffffff or nid in native_ids:
            raise ValueError('Invalid or duplicate native squad identity')
        native_ids.add(nid)
        if r.name and r.name in names:raise ValueError('Duplicate squad name')
        if r.name:names.add(r.name)
        if r.formation_id is not None: validate_formation(r.formation_id)
        if type(r.manager_id) is not int or r.manager_id not in managers:
            raise ValueError('Squad manager is not owned')
        if r.summary is not None and (type(r.summary) is not SquadSummary or
                any(type(v) is not int or not 0 <= v <= 100 for v in asdict(r.summary).values())):
            raise ValueError('Invalid client squad summary')
        slots = set(); players = set()
        for slot in r.lineup:
            if (type(slot) is not SquadSlot or type(slot.index) is not int or not 0 <= slot.index < 23 or
                    slot.index in slots or slot.instance_id in players or slot.instance_id not in owned or
                    slot.instance_id in trade):
                raise ValueError('Invalid saved squad player reference')
            slots.add(slot.index); players.add(slot.instance_id)
    retired = state.retired_squad_ids
    if len(set(retired)) != len(retired) or any(type(i) is not int or i < 0 or i in ids for i in retired):
        raise ValueError('Invalid retired squad identity')
    native_retired=state.retired_native_squad_ids
    if (len(set(native_retired))!=len(native_retired) or
            any(type(i) is not int or not 0<=i<0x7fffffff for i in native_retired)):
        raise ValueError('Invalid retired native squad identity')
    if (type(state.next_squad_id) is not int or
            not max(ids | set(retired), default=0) < state.next_squad_id <= 0x7fffffff):
        raise ValueError('Invalid squad identity counter')
    seen = set()
    for receipt in state.squad_creations:
        if (type(receipt) is not SquadCreation or len(receipt.body_sha256) != 64 or
                any(c not in '0123456789abcdef' for c in receipt.body_sha256) or receipt.body_sha256 in seen or
                type(receipt.request_id) is not int or not 0 <= receipt.request_id < 0x7fffffff or
                receipt.squad_id not in ids | set(retired)):
            raise ValueError('Invalid squad creation receipt')
        seen.add(receipt.body_sha256)


def put(state, record):
    if record.id == state.squad_id:
        from .local_football import activate_manager
        state = activate_manager(state, record.manager_id)
        manager = state.squad_manager_id
        current_manager = state.active_manager.instance_id if state.active_manager else 0
        if record.manager_id != current_manager or manager is not None:
            manager = record.manager_id
        return replace(state, active_lineup=record.lineup, formation_id=record.formation_id,
                       squad_name=record.name, squad_summary=record.summary, squad_manager_id=manager,
                       squad_native_id=record.native_id)
    if get(state, record.id) is None:
        raise ValueError('Unknown saved squad')
    return replace(state, other_squads=tuple(record if r.id == record.id else r for r in state.other_squads))


def creation_digest(body,session_id=None,squad_id=None):
    if session_id is None:return hashlib.sha256(body).hexdigest()
    if type(session_id) is not str or not session_id.startswith('fifa16-pack-') or len(session_id)!=44 or type(squad_id) is not int or squad_id<0:raise ValueError('Invalid squad creation session')
    return hashlib.sha256(b'current_session_squad_authority_v1\0'+session_id.encode()+b'\0'+str(squad_id).encode()+b'\0'+body).hexdigest()


def create(state, update, body,*,session_id=None):
    digest = creation_digest(body)
    previous = (next((r for r in state.squad_creations if r.body_sha256==digest),None) if session_id is None else
        next((r for r in reversed(state.squad_creations) if r.request_id==update.squad_id and
            get(state,r.squad_id) is not None and r.body_sha256==creation_digest(body,session_id,r.squad_id)),None))
    if previous:
        if previous.squad_id in state.retired_squad_ids:
            raise ValueError('Cannot resurrect a deleted squad with an old creation retry')
        return state, previous.squad_id
    if not update.name or any(r.name == update.name for r in records(state)):
        raise ValueError('Squad name must be unique')
    if by_native_id(state, update.squad_id) is not None:
        raise ValueError('Native squad identity is already occupied')
    sid = state.next_squad_id
    if sid >= 0x7fffffff: raise ValueError('Squad IDs exhausted')
    if session_id is not None:digest=creation_digest(body,session_id,sid)
    record = SquadRecord(sid, update.name, update.lineup, update.formation_id, update.manager_id, update.summary,
                         update.squad_id if update.squad_id != sid else None)
    return replace(state, other_squads=state.other_squads+(record,), next_squad_id=sid+1,
                   squad_creations=state.squad_creations+(SquadCreation(digest, sid, update.squad_id),)), sid


def select(state, squad_id):
    target = get(state, squad_id)
    if target is None: raise ValueError('Unknown squad selection')
    if squad_id == state.squad_id: return state
    others = tuple(sorted((active_record(state), *(r for r in state.other_squads if r.id != squad_id)), key=lambda r: r.id))
    state = replace(state, squad_id=target.id, squad_name=target.name, squad_summary=target.summary,
                    active_lineup=target.lineup, formation_id=target.formation_id,
                    squad_manager_id=target.manager_id, squad_native_id=target.native_id, other_squads=others)
    # A saved squad may name another owned manager: it becomes the active one.
    from .local_football import activate_manager, item_pile
    if (target.manager_id and any(m.instance_id == target.manager_id for m in state.owned_managers)
            and item_pile(state, target.manager_id) == 'club'):
        state = activate_manager(state, target.manager_id)
    return state


def bind_pending_creation_native_id(state, body):
    """Migrate the archived 896 empty creation without replaying its edit.

    The first implementation replied with a server ID; original021dc168/Lua
    uses its synchronous lowest-free ID instead. Keep the durable identity and
    receipt, binding only that still-empty creation to its observed wire ID.
    """
    digest = hashlib.sha256(body).hexdigest()
    receipt = next((r for r in state.squad_creations if r.body_sha256 == digest), None)
    if receipt is None: raise ValueError('Captured creation receipt required')
    record = get(state, receipt.squad_id)
    if record is None or record.lineup: raise ValueError('Only the empty pending creation may be bound')
    existing = by_native_id(state, receipt.request_id)
    if existing is not None and existing.id != record.id: raise ValueError('Native identity conflicts')
    return put(state, replace(record, native_id=receipt.request_id if receipt.request_id != record.id else None))


def delete(state, squad_id):
    """Retire an inactive squad reference, never its owned items.

    Original management disables deletion of the current squad (892). A
    retained tombstone makes the captured ID safe to retry across restarts.
    """
    if type(squad_id) is not int or squad_id < 0:
        raise ValueError('Invalid squad deletion identity')
    if squad_id in state.retired_squad_ids:
        return state
    if squad_id == state.squad_id:
        raise ValueError('Cannot delete the current squad')
    if get(state, squad_id) is None:
        raise ValueError('Unknown squad deletion')
    return replace(state, other_squads=tuple(r for r in state.other_squads if r.id != squad_id),
                   retired_squad_ids=tuple(sorted((*state.retired_squad_ids, squad_id))),
                   retired_native_squad_ids=tuple(sorted(set(state.retired_native_squad_ids)|{wire_id(get(state,squad_id))})))
