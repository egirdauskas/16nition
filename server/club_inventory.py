"""Shared route5 ClubSearch: typed filters and authoritative club ownership."""
from urllib.parse import urlsplit,parse_qs
from functools import lru_cache
from .game_auth import SID
from .identity import json_response
from .local_football import item_pile
from .football_protocol import encode_item,encode_consumable,encode_manager
from .reconstructed_specials import display_rating
PATH='/ut/game/fifaworldmobile/club'
@lru_cache(maxsize=1)
def premier_teams():
    # Observed league13/club7 filter in run354; IDs resolve from shipped links.
    from .local_content_source import DB,META,cards
    from scripts.local_football_db import FootballDB
    cards();db=FootballDB(DB,META);limit=db.table('futleagueteamlinks')['valid_count']
    return frozenset(r['teamid'] for r in db.rows('futleagueteamlinks',['teamid','leagueid']) if r['row_index']<limit and r['leagueid']==13)

def response_for(method,target,headers,body,store):
    if (method!='GET' or body or headers.get(b'host')!=b'10.0.2.2:18081' or
        headers.get(b'x-ut-sid')!=SID.encode() or headers.get(b'content-length',b'0')!=b'0'):return None
    try:
        url=urlsplit(target)
        if url.scheme or url.netloc or url.fragment or url.path!=PATH:return None
        query=parse_qs(url.query,keep_blank_values=True,strict_parsing=True)
        from .club_item_actions import search as club_item_search
        reply=club_item_search(query,store)
        if reply is not None:return reply
        from .consumable_effects import features
        if query.get('type')==['development'] and 'inventory_search' in features(store):
            from .club_player_search import integer
            if (set(query) not in ({'type','level','count'},{'type','level','count','start'}) or
                    any(len(v)!=1 for v in query.values()) or query['level']!=['any']):return None
            count=integer(query['count'][0],1,0x7fffffff)
            start=integer(query.get('start',['0'])[0],0,0x7fffffff)
            state=store.load(1)
            items=sorted((i for i in state.owned_consumables if item_pile(state,i.instance_id)=='club'),key=lambda i:i.instance_id)
            # Original InventoryModel.searchConsumables asks for65 at offset0;
            # InventorySearch pages use12. ConsumablesPopup._publishResults
            # raises on misc redeemables despite its broad filter. Position18
            # is the original TACTIC_TRAINING branch, admitted separately only
            # when its effect is enabled. Keep all owned cards in Inventory.
            if count==65 and start==0:
                from .local_consumables import inventory_reference,INJURY_SUBTYPES
                from .consumable_effects import PLAYER_FORMATIONS,MANAGER_FORMATIONS,TRAINING_SUBTYPES,POSITION_PAIRS
                supported=frozenset(PLAYER_FORMATIONS)|frozenset(MANAGER_FORMATIONS)|TRAINING_SUBTYPES|INJURY_SUBTYPES
                if 'position' in features(store):supported|=frozenset(POSITION_PAIRS)
                items=[i for i in items if inventory_reference(i.resource_id)['cardsubtype'] in supported]
            return json_response({'itemData':[encode_consumable(i,store.path.parent) for i in items[start:start+count]]})
        if query.get('type') == ['manager']:
            # 893 original AddManager: the shared ClubSearch decoder consumes
            # supplied subtype4 manager records. Stock manager filters are
            # disabled; paging still uses canonical count/start, not one URL.
            from .club_player_search import integer
            if (set(query) not in ({'type','level','count'}, {'type','level','count','start'}) or
                    any(len(v) != 1 for v in query.values()) or query['level'] != ['any']):
                return None
            count = integer(query['count'][0], 1, 0x7fffffff)
            start = integer(query.get('start', ['0'])[0], 0, 0x7fffffff)
            state = store.load(1); manager = state.active_manager
            items = [manager] if manager is not None and item_pile(state, manager.instance_id) == 'club' else []
            items += [m for m in state.owned_managers if item_pile(state, m.instance_id) == 'club']
            return json_response({'itemData':[encode_manager(i) for i in items[start:start+count]]})
        development={'type':['development'],'level':['any'],'count':['65']}
        from .native_club_statistics import selected as isolated_inventory
        inventory_page={'type':['development'],'level':['any'],'count':['12']}
        # Original InventorySearch requests11visible items plus one lookahead;
        #684 captures start11/count12. Lua computes pageIndex*11 thereafter.
        offset=query.get('start',[]) if query.keys()==inventory_page.keys()|{'start'} else []
        paged=(len(offset)==1 and offset[0].isascii() and offset[0].isdecimal()
               and str(int(offset[0]))==offset[0] and int(offset[0])>=11 and int(offset[0])%11==0
               and {k:v for k,v in query.items() if k!='start'}==inventory_page)
        if query==development or ((query==inventory_page or paged) and isolated_inventory(store)):
            state=store.load(1)
            items=[i for i in state.owned_consumables if item_pile(state,i.instance_id)=='club']
            count=int(query['count'][0])
            start=int(offset[0]) if paged else 0
            return json_response({'itemData':[encode_consumable(i,store.path.parent) for i in sorted(items,key=lambda i:i.instance_id)[start:start+count]]})
        from .club_player_search import PlayerQuery
        search=PlayerQuery.decode(query)
        state=store.load(1)
        items=search.select(state,store.catalog)
        return json_response({'itemData':[encode_item(i,store.catalog,True,store.path.parent) for i in items]})
    except (ValueError,TypeError):return None
