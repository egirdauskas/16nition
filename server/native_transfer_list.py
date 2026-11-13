"""Explicit captured Store-player transfer storage; no auctions or market sales."""
from pathlib import Path
ACCOUNT=None
TRAINING=False
CAPACITY=30  # Original item context in capture731 displays TO TRANSFER0/30.

def configure(account=None,*,training=False):
    global ACCOUNT,TRAINING
    ACCOUNT=None;TRAINING=False
    if type(training) is not bool or (training and account is None):raise ValueError('Training transfer requires explicit account')
    if account is not None:
        from .store_release import projection_account
        account=Path(account).resolve()
        ACCOUNT=projection_account([account/n for n in
            ('profile.json','football.json','content.json','packs.json','seasons.json','definition.json','control.json')])
        TRAINING=training

def selected(store):
    return ACCOUNT is not None and store.path.resolve().parent==ACCOUNT

def response_for(method,target,headers,body,store):
    """02305348→0102a320 shares the proven auctionInfo/itemData parser.

    An unlisted owned item uses inactive state2/tradeId0. The native retained
    handle uses the pair (trade ID, owned instance ID), not a fabricated sale.
    """
    from .game_auth import SID
    if (not selected(store) or method!='GET' or target!='/ut/game/fifaworldmobile/tradePile' or
        body or headers.get(b'host')!=b'10.0.2.2:18081' or headers.get(b'x-ut-sid')!=SID.encode() or
        headers.get(b'content-length',b'0')!=b'0'):return None
    from .local_football import item_pile
    from .football_protocol import encode_item,encode_consumable,encode_owned_club_item
    from .identity import json_response
    state=store.load(1)
    items=[encode_item(i,store.catalog,True,store.path.parent) for i in state.owned_items if item_pile(state,i.instance_id)=='trade']
    items += [encode_consumable(i,store.path.parent) for i in state.owned_consumables if item_pile(state,i.instance_id)=='trade']
    from .club_item_actions import transfer_storage_enabled
    if transfer_storage_enabled(store):
        items += [encode_owned_club_item(i,store.path.parent) for i in state.owned_club_items if item_pile(state,i.instance_id)=='trade']
    from .football_protocol import encode_manager
    items += [encode_manager(m) for m in state.owned_managers if item_pile(state,m.instance_id)=='trade']
    items.sort(key=lambda i:i['id'])
    rows=[{'tradeId':0,'tradeState':'inactive','itemData':i} for i in items]
    # MARKET-003: listed/expired/sold rows come from the market store (lab only).
    from .market_protocol import tradepile_rows
    rows=tradepile_rows(store.path.parent,rows)
    return json_response({'auctionInfo':rows})

def market_tradeable(state,instance_id):
    """Market v1: consumable families, club items and spare managers may enter the Transfer List."""
    if ACCOUNT is None:return False
    from .market_protocol import items_tradeable
    return items_tradeable(ACCOUNT,state,instance_id)

def moves_allowed(state,moves,*,club_items=False):
    from .local_football import item_pile
    if ACCOUNT is not None:
        from .market_protocol import escrowed
        listed=escrowed(ACCOUNT)
        if any(move.instance_id in listed for move in moves):raise ValueError('Listed item is in escrow')
    # Store-item movement into storage or return to club, never another owner.
    for move in moves:
        if move.pile=='trade':
            if move.instance_id in state.untradeable_instance_ids:raise ValueError('Untradeable reward cannot transfer')
            player=next((i for i in state.owned_items if i.instance_id==move.instance_id),None)
            if player is None:
                club=next((i for i in state.owned_club_items if i.instance_id==move.instance_id),None)
                from .local_consumables import inventory_references,pack_references,CURRENT_POOL
                item=next((i for i in state.owned_consumables if i.instance_id==move.instance_id),None)
                if not ((club_items and club is not None) or
                        (TRAINING and item is not None and item.resource_id in inventory_references() and
                        item.resource_id in pack_references(CURRENT_POOL)) or
                        market_tradeable(state,move.instance_id)):
                    raise ValueError('Only certified player/supported training transfer storage is enabled')
            if any(s.instance_id==move.instance_id for s in state.active_lineup):raise ValueError('Active player cannot transfer')
            if any(s.instance_id==move.instance_id for squad in state.other_squads for s in squad.lineup):
                raise ValueError('Remove player from saved squads before transfer')
        if item_pile(state,move.instance_id) not in ('unassigned','club','trade'):raise ValueError('Unknown source pile')
    current={i.instance_id for i in state.inventory_locations if i.pile=='trade'}
    for move in moves:
        if move.pile=='trade':current.add(move.instance_id)
        else:current.discard(move.instance_id)
    if len(current)>CAPACITY:raise ValueError('Transfer storage full')
