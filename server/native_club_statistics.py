"""Opt-in club totals for captured route6 and original parser0103e514.

Wire keys/type names come from the supplied RS4 dictionary. Context1 normalizes
to the aggregate cache key0 read by the original Inventory tiles. Counts are
derived from current club ownership; this is not historical account data.
"""
from pathlib import Path
from .game_auth import SID
from .identity import json_response
from .local_football import item_pile
from .reconstructed_specials import display_rating

PATH = '/ut/game/fifaworldmobile/club/stats/year'
NEWCARDS_PATH = '/ut/game/fifaworldmobile/club/stats/newcards'
ACCOUNT = None


def configure(account=None):
    global ACCOUNT
    ACCOUNT = Path(account).resolve() if account is not None else None


def selected(store):
    if ACCOUNT is not None and store.path.resolve().parent == ACCOUNT:return True
    from .consumable_effects import features
    return 'inventory_search' in features(store)


def statistics(store):
    state = store.load(1)
    club = lambda item: item_pile(state, item.instance_id) == 'club'
    players = [item for item in state.owned_items if club(item)]
    levels = [display_rating(item) for item in players]
    manager = int(state.active_manager is not None and club(state.active_manager))
    values = {
        'players': len(players),
        'playersBronze': sum(rating < 65 for rating in levels),
        'playersSilver': sum(65 <= rating < 75 for rating in levels),
        'playersGold': sum(rating >= 75 for rating in levels),
        'staffManager': manager,
        'stadia': sum(item.item_type == 'stadium' and club(item) for item in state.active_club_items+state.owned_club_items),
        'kits': sum(item.item_type == 'kit' and club(item) for item in state.active_club_items+state.owned_club_items),
        'badges': int(state.active_badge is not None and club(state.active_badge))+sum(item.item_type=='badge' and club(item) for item in state.owned_club_items),
        'consumables': sum(club(item) for item in state.owned_consumables),
    }
    if any(item.item_type=='ball' for item in state.owned_club_items+state.active_club_items):
        values['balls']=sum(item.item_type=='ball' and club(item) for item in state.owned_club_items+state.active_club_items)
    return {'stat': [{'contextId': 1, 'contextValue': 0, 'type': name, 'typeValue': value}
                     for name, value in values.items()]}


def response_for(method, target, headers, body, store):
    if (not selected(store) or
        method != 'GET' or target not in (PATH, NEWCARDS_PATH) or body or
        headers.get(b'host') != b'10.0.2.2:18081' or
        headers.get(b'x-ut-sid') != SID.encode() or
        headers.get(b'content-length', b'0') != b'0'):
        return None
    return json_response(statistics(store))
