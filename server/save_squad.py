"""Existing squad0 roles ACK and opt-in stock player/formation persistence.

Factory0103c474 initializes optional response+28 id to0; parser0103cbdc
accepts{}. Full edit delegate021e10d8→021daf18 clears pending/publishes event6d.
Roles-only no-op00b74fd8 behaviour is unchanged. Domain changes are committed
only for validated full edits immediately before the acknowledgement is sent.
"""
import json
from .game_auth import SID
from .identity import json_response

PATH = '/ut/game/fifaworldmobile/squad/0'

def validate_roles(value,state,squad_id=0,*,wire_squad_id=None):
    if (type(value) is not dict or set(value)!={'id','captain','kicktakers'} or
        type(value['id']) is not int or value['id']!=(squad_id if wire_squad_id is None else wire_squad_id) or type(value['captain']) is not int or
        type(value['kicktakers']) is not list or len(value['kicktakers'])!=5):return False
    from .local_squads import get
    record=get(state,squad_id)
    if record is None:return False
    owned={item.instance_id for item in state.owned_items}
    squad={slot.instance_id for slot in record.lineup}
    if value['captain'] not in owned & squad:return False
    indices=set()
    for role in value['kicktakers']:
        if (type(role) is not dict or set(role)!={'index','id'} or type(role['index']) is not int or
            not 0<=role['index']<5 or role['index'] in indices or type(role['id']) is not int or
            role['id'] not in owned & squad):return False
        indices.add(role['index'])
    return True

def response_for(method, target, headers, body, football_store, mutations_enabled=False):
    if mutations_enabled:
        from .squad_management import response_for as management_response
        reply=management_response(method,target,headers,body,football_store)
        if reply is not None:return reply
    if (method != 'PUT' or target != PATH
            or headers.get(b'host') != b'10.0.2.2:18081'
            or headers.get(b'x-ut-sid') != SID.encode()
            or headers.get(b'content-type') != b'application/json'):
        return None
    try:
        if b'content-length' in headers and int(headers[b'content-length']) != len(body):
            return None
        value = json.loads(body)
        if mutations_enabled and type(value) is dict and 'players' in value:
            from .squad_mutation import decode
            decode(body,football_store.load(1))
            return json_response({}) # Validation only; commit immediately before send.
        state = football_store.load(1)
        if not validate_roles(value,state):return None
        return json_response({})
    except (ValueError, UnicodeError, TypeError):
        return None

def commit_request(method,target,headers,body,football_store,mutations_enabled=False):
    """No state write during preliminary response probes or diagnostic holds."""
    if not mutations_enabled:return
    from .squad_management import commit_request as management_commit,selected
    if selected(football_store):
        response=management_commit(method,target,headers,body,football_store)
        if response is not None:return response
    reply=response_for(method,target,headers,body,football_store,mutations_enabled=True)
    if reply is None:raise ValueError('Invalid squad request cannot be committed')
    value=json.loads(body)
    if 'players' not in value:return # Existing role-only acknowledgement unchanged.
    from .squad_mutation import decode
    update=decode(body,football_store.load(1))
    football_store.update_squad(1,update.lineup,update.formation_id,name=update.name,summary=update.summary,
                                manager_id=update.manager_id)
