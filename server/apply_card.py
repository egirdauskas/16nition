"""Captured route29 ApplyCard: typed target delta + consumed ownership.

Factory0103158c, responseVT027aaac8, parser010318f4 itemData/shared
01028fc0. Frontend00b60dcc removes selected consumable and emits event5a.
GK training uses a resource reference; manager modifiers use formation.
No static manager/player metadata, coins or rewards are changed.
"""
import json,re
from pathlib import Path
from .game_auth import SID
from .identity import json_response
from .football_protocol import encode_item,encode_manager
from .local_football import OwnedManagerItem
PREFIX='/ut/game/fifaworldmobile/item/'
PLAYER_FORMATION_ACCOUNT=None

def configure_player_formation(account=None):
    global PLAYER_FORMATION_ACCOUNT
    PLAYER_FORMATION_ACCOUNT=None
    if account is not None:
        from .startup import validate_simulation_discovery
        path=Path(account).resolve()
        validated=validate_simulation_discovery([path/n for n in
            ('profile.json','football.json','content.json','packs.json','seasons.json','definition.json','control.json')])
        if validated.name!='isolated-account':raise ValueError('Player formation is isolated-only')
        PLAYER_FORMATION_ACCOUNT=validated

def player_formation_enabled(store):
    return PLAYER_FORMATION_ACCOUNT is not None and store.path.resolve().parent==PLAYER_FORMATION_ACCOUNT


def encode_target(item,store):
    return encode_manager(item) if type(item) is OwnedManagerItem else encode_item(item,store.catalog,True,store.path.parent)


def is_source_path(target):
    """ApplyCard owns only item/<numeric source>, not item subservices."""
    return re.fullmatch(re.escape(PREFIX)+r'[1-9][0-9]*',target) is not None


def decode(method,target,headers,body):
    if (method!='POST' or headers.get(b'host')!=b'10.0.2.2:18081' or
        headers.get(b'x-ut-sid')!=SID.encode() or headers.get(b'content-type')!=b'application/json' or
        headers.get(b'content-length')!=str(len(body)).encode() or
        not is_source_path(target)):
        raise ValueError('Not the captured authenticated ApplyCard route')
    consumable=int(target[len(PREFIX):]);value=json.loads(body)
    if (type(value) is not dict or set(value)!={'apply'} or type(value['apply']) is not list or
        len(value['apply'])!=1 or type(value['apply'][0]) is not dict or set(value['apply'][0])!={'id'} or
        type(value['apply'][0]['id']) is not int):raise ValueError('Unmapped ApplyCard body')
    return consumable,value['apply'][0]['id']

def response_for(method,target,headers,body,store):
    try:
        consumable,target_id=decode(method,target,headers,body)
        from .consumable_effects import guard_training_application
        guard_training_application(store,consumable)
        from .consumable_effects import features
        _,player=store.preview_consumable_application(store.load(1),consumable,target_id,player_formation=player_formation_enabled(store),extended_effects=features(store))
    except (ValueError,TypeError,UnicodeError,KeyError):return None
    return json_response({'itemData':[encode_target(player,store)]})

def commit_request(method,target,headers,body,store):
    consumable,target_id=decode(method,target,headers,body)
    from .consumable_effects import guard_training_application
    guard_training_application(store,consumable)
    from .consumable_effects import features
    player=store.apply_consumable(1,consumable,target_id,player_formation=player_formation_enabled(store),extended_effects=features(store))
    return json_response({'itemData':[encode_target(player,store)]})
