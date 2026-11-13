"""Captured route2d MoveCard: unassigned owned instances → club.

Response VT027aabc8/parser01036570, frontend00b61600. Per-record success
updates unassigned counts and event37. Never creates players or economy state.
"""
import json,re
from .game_auth import SID
from .identity import json_response
from .local_football import ItemLocation,owned_instance_ids,item_pile
from .local_profile import load_profile

PATH='/ut/game/fifaworldmobile/item'
DISCARD_PREFIX='/ut/delete/game/fifaworldmobile/item/'

def discard_id(method,target,headers,body,state):
    """Only the captured zero-value unassigned duplicate-player branch.

    No club/active removal, sale valuation or economy grant is inferred from
    GET. Retired IDs are persisted receipts, allowing a lost ACK to be retried.
    """
    if (method!='GET' or body or headers.get(b'host')!=b'10.0.2.2:18081' or
        headers.get(b'x-ut-sid')!=SID.encode() or headers.get(b'content-length',b'0')!=b'0'):
        return None
    if not re.fullmatch(re.escape(DISCARD_PREFIX)+r'[1-9][0-9]*',target):return None
    iid=int(target[len(DISCARD_PREFIX):])
    if iid>0x7fffffffffffffff:return None
    if iid in state.retired_instance_ids:return iid
    item=next((i for i in state.owned_items if i.instance_id==iid),None)
    if (item is None or item_pile(state,iid)!='unassigned' or
        any(s.instance_id==iid for s in state.active_lineup)):return None
    from .reconstructed_specials import player_version_key
    if not any(i.instance_id!=iid and player_version_key(i)==player_version_key(item) and
               item_pile(state,i.instance_id)=='club' for i in state.owned_items):return None
    return iid

def decode_move(body,state,*,transfer=False,club_items=False):
    value=json.loads(body)
    if type(value) is not dict or set(value)!={'itemData'} or type(value['itemData']) is not list or not 1<=len(value['itemData'])<=100:
        raise ValueError('Unmapped inventory-move envelope')
    owned=owned_instance_ids(state);seen=set();moves=[]
    for item in value['itemData']:
        if (type(item) is not dict or set(item)!={'id','pile','swap','tradeId'} or
            type(item['id']) is not int or item['id'] not in owned or item['id'] in seen or
            item['pile'] not in (('club','trade') if transfer else ('club',)) or type(item['swap']) is not int or item['swap']!=0 or
            type(item['tradeId']) is not int or item['tradeId']!=0):
            raise ValueError('Unsupported/unknown inventory placement')
        seen.add(item['id']);moves.append(ItemLocation(item['id'],item['pile']))
    if transfer:
        from .native_transfer_list import moves_allowed
        moves_allowed(state,moves,club_items=club_items)
    return tuple(moves)

def response_for(method,target,headers,body,store):
    from .native_quick_sell_protocol import response_for as quick_sell_response
    reply=quick_sell_response(method,target,headers,body,store)
    if reply is not None:return reply
    from .native_quick_sell_protocol import selected as quick_sell_selected, PREFIX as QUICK_SELL
    if quick_sell_selected(store.path.parent) and target.startswith(QUICK_SELL):return None
    from .native_transfer_list import response_for as transfer_response
    reply=transfer_response(method,target,headers,body,store)
    if reply is not None:return reply
    if method=='GET':
        if not target.startswith(DISCARD_PREFIX):return None
        iid=discard_id(method,target,headers,body,store.load(1))
        if iid is None:return None
        # Parser01033b08: totalCredits+28 and items[id64]+2c/30. Internal
        # 01a5bec0 installs this balance;00b61188 removes returned IDs and
        # decrements unassigned count. {} would install0 and retire no items.
        return json_response({'totalCredits':load_profile().credits,'items':[{'id':iid}]})
    if (method!='PUT' or target!=PATH or headers.get(b'host')!=b'10.0.2.2:18081' or
        headers.get(b'x-ut-sid')!=SID.encode() or headers.get(b'content-type')!=b'application/json' or
        headers.get(b'content-length')!=str(len(body)).encode()):return None
    from .native_transfer_list import selected
    from .club_item_actions import transfer_storage_enabled
    try:moves=decode_move(body,store.load(1),transfer=selected(store),club_items=transfer_storage_enabled(store))
    except (ValueError,TypeError,UnicodeError,KeyError):return None
    return json_response({'itemData':[{'id':m.instance_id,'pile':m.pile,'success':True} for m in moves]})

def commit_request(method,target,headers,body,store):
    from .native_quick_sell_protocol import commit_request as commit_quick_sell
    reply=commit_quick_sell(method,target,headers,body,store)
    if reply is not None:return reply
    from .native_quick_sell_protocol import selected as quick_sell_selected, PREFIX as QUICK_SELL
    if quick_sell_selected(store.path.parent) and target.startswith(QUICK_SELL):raise ValueError('Cannot commit invalid quick sell')
    if method=='GET' and target.startswith(DISCARD_PREFIX):
        iid=discard_id(method,target,headers,body,store.load(1))
        if iid is None:raise ValueError('Cannot commit invalid discard request')
        return store.mutate_inventory(1,remove_ids=(iid,))
    if method!='PUT' or target!=PATH:return
    if response_for(method,target,headers,body,store) is None:raise ValueError('Cannot commit invalid inventory request')
    from .native_transfer_list import selected
    from .club_item_actions import transfer_storage_enabled
    moves=decode_move(body,store.load(1),transfer=selected(store),club_items=transfer_storage_enabled(store))
    return store.mutate_inventory(1,locations=moves)
