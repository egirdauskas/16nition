"""Observed starting-eleven/substitution ACK. Fieldless01059228/no-op01045cd0.

Accept the current eleven starters or one owned lineup participant, as observed
on an injury substitution in run276. Run362 additionally emits the same
eleven starters plus the exact active manager. No lineup/condition writes.
"""
import json
from .game_auth import SID
from .identity import json_response
PATH = '/ut/game/fifaworldmobile/match'

def response_for(method, target, headers, body, football_store, *, allow_substitutions=False):
    if (method != 'PUT' or target != PATH
            or headers.get(b'host') != b'10.0.2.2:18081'
            or headers.get(b'x-ut-sid') != SID.encode()
            or headers.get(b'content-type') != b'application/json'):
        return None
    try:
        if b'content-length' in headers and int(headers[b'content-length']) != len(body):
            return None
        value = json.loads(body)
        if type(value) is not dict or set(value) != {'items'} or type(value['items']) is not list or not value['items']:
            return None
        if not allow_substitutions and len(value['items']) not in (1, 11, 12):return None
        ids = []
        for item in value['items']:
            if type(item) is not dict or set(item) != {'id'} or type(item['id']) is not int:
                return None
            ids.append(item['id'])
        state = football_store.load(1)
        starters = {slot.instance_id for slot in state.active_lineup if slot.index < 11}
        lineup = {slot.instance_id for slot in state.active_lineup}
        owned = {item.instance_id for item in state.owned_items}
        from .local_squads import active_record
        manager_id=active_record(state).manager_id
        manager={manager_id} if manager_id else set()
        if allow_substitutions:
            #878/879 send one/two incoming players through the same vector.
            #The active played coordinator opts in after initial roster ACK.
            #Accept every nonempty distinct subset of this squad's players;
            #the client owns substitution limits and the in-match lineup.
            if len(set(ids))!=len(ids) or not set(ids)<=lineup & owned:return None
            return json_response({})
        if len(set(ids)) != len(ids) or not set(ids) <= owned | manager:
            return None
        if len(ids) == 12 and (len(starters) != 11 or not manager or set(ids) != starters | manager):
            return None
        if (len(ids) == 11 and set(ids) != starters) or (len(ids) == 1 and not set(ids) <= lineup):
            return None
        return json_response({})
    except (ValueError, UnicodeError, TypeError):
        return None
