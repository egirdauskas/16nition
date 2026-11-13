"""Transport-only interventions for captured post-auth dependencies.

No protocol payloads. Hold/release exact local authenticated requests to prove
causality. The first unknown game request may be held without a response.
A control file is reread so release does not require client restart.
"""
import json
from pathlib import Path
import time
from urllib.parse import urlsplit, parse_qs

def dependency(data):
    lines = data.split(b'\r\n')
    try:
        method, target, version = lines[0].decode().split()
    except ValueError:
        return None
    headers = {line.split(b':', 1)[0].lower(): line.split(b':', 1)[1].strip()
               for line in lines[1:] if b':' in line}
    if headers.get(b'host') != b'10.0.2.2:18081':
        return None
    url = urlsplit(target)
    path = url.path
    query = parse_qs(url.query)
    if (method == 'GET' and path == '/connect/auth'
            and query.get('client_id') == ['FIFA-WORLD-MOBILE-SERVER-ANDROID']
            and query.get('response_type') == ['code']
            and query.get('access_token') == ['fifa16-local-access']
            and query.get('redirect_uri') == ['nucleus:rest']):
        return 'victorycode'
    if path.startswith('/victory_fwm_s2/'):return 'victory'
    if headers.get(b'x-ut-sid') != b'fifa16-local-sid':return None
    if method=='GET':
        known={'/ut/game/fifaworldmobile/settings': 'settings',
               '/ut/game/fifaworldmobile/user': 'userinfo',
               '/ut/game/fifaworldmobile/purchased/items': 'purchased',
               '/ut/mm/game/FifaWorldMobile/message/list': 'messages'}.get(path)
        if known:return known
    if method=='PUT' and path=='/ut/game/fifaworldmobile/match/reset':return 'reset'
    if method=='PUT' and path=='/ut/game/fifaworldmobile/item' and not url.query:return 'inventory'
    # Captured Android DiscardCard uses GET on a /ut/delete/ URI (run285).
    delete_prefix='/ut/delete/game/fifaworldmobile/item/'
    suffix=path[len(delete_prefix):] if path.startswith(delete_prefix) else ''
    if (method=='GET' and not url.query and suffix.isascii() and suffix.isdecimal()
        and suffix==str(int(suffix)) and 0<int(suffix)<=0x7fffffffffffffff):return 'inventory'
    # Genuine Quick Sell All query captured731; same inventory control as single.
    if method=='GET' and path==delete_prefix[:-1]:
        from .native_quick_sell_protocol import decode
        from .http_framing import split_head
        try:decode(method,target,checked_session_headers(headers),split_head(data)[1]);return 'inventory'
        except (ValueError,TypeError):pass
    # Original DeleteSquad uses a GET on this legacy delete URI (892).
    if method=='GET' and path.startswith('/ut/delete/game/fifaworldmobile/squad/'):
        return 'successor'
    if path.startswith('/ut/game/fifaworldmobile/'):return 'successor'
    return None

def checked_session_headers(headers):
    """Use the same validated original SID boundary as the HTTP adapters."""
    from .native_pack_sessions import normalize,is_stale
    value=normalize(headers)
    if is_stale(value):raise ValueError('Closed native session')
    return value

def owned_player_price_query(data, football_state, football_catalog=None, *, unassigned=False):
    """Captured full player-set query, order independent; no market payload.

    Squad edits reorder this request. Preserve the observed failure-tolerant EOF
    only for the established owned PLAYER set, excluding badge/kits/stadium.
    """
    if not data or not football_state:return False
    try:
        from .http_framing import split_head
        head,body,_=split_head(data)
        lines=head.split(b'\r\n');method,target,version=lines[0].decode('ascii').split()
        headers={line.split(b':',1)[0].lower():line.split(b':',1)[1].strip() for line in lines[1:] if b':' in line}
        headers=checked_session_headers(headers)
        if (method!='GET' or version!='HTTP/1.1' or body or
            headers.get(b'host')!=b'10.0.2.2:18081' or
            headers.get(b'x-ut-sid')!=b'fifa16-local-sid'):return False
        url=urlsplit(target)
        if url.scheme or url.netloc or url.fragment or url.path!='/ut/game/fifaworldmobile/marketdata/item/pricelimits':return False
        query=parse_qs(url.query,keep_blank_values=True,strict_parsing=True)
        if set(query)!={'itemIdList'} or len(query['itemIdList'])!=1:return False
        raw=query['itemIdList'][0].split(',')
        if raw!=[''] and not all(v.isascii() and v.isdecimal() and str(int(v))==v for v in raw):return False
        ids=[] if raw==[''] else [int(v) for v in raw]
        from .local_football import FootballStore,owned_instance_ids,item_pile
        from .local_content import ContentCatalog
        state=FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None).load(1)
        if unassigned:
            expected={i for i in owned_instance_ids(state) if item_pile(state,i)=='unassigned'}
            #1023: the client queues a complete price lookup before its Redeem
            #callback removes the source. The durable retirement may commit
            #first; holding that read also blocks the callback/wallet refresh.
            #Keep the existing failure-tolerant EOF for this same-account stale
            #snapshot. Require every current item; extras must be authoritative
            #retired ownership IDs, never foreign IDs or another current pile.
            requested=set(ids)
            return (bool(ids) and len(ids)==len(requested) and expected<=requested and
                    requested<=expected|set(state.retired_instance_ids))
        owned={i.instance_id for i in state.owned_items}
        squad={s.instance_id for s in state.active_lineup}
        sets=(owned,squad)
        from .squad_management import selected as squad_management_selected
        named_squads=squad_management_selected(FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None))
        if named_squads:
            from .local_squads import records
            # Viewing/building an inactive squad emits its complete roster too.
            # Preserve the known EOF behavior for every saved roster, never an
            # arbitrary owned subset or invented Transfer Market price payload.
            sets+=tuple({s.instance_id for s in record.lineup} for record in records(state))
        from .native_transfer_list import selected
        store=FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None)
        if selected(store):
            # Original733 captures this complete owned transfer-storage set.
            # Preserve the existing failure-tolerant EOF; no market prices.
            sets+=(set(i for i in owned_instance_ids(state) if item_pile(state,i)=='trade'),)
        # A new unassigned grant need not appear in the existing squad query.
        return (bool(ids) or named_squads and set() in sets) and len(ids)==len(set(ids)) and set(ids) in sets
    except (ValueError,TypeError,UnicodeError,KeyError,OSError):return False

def validated_club_filter(data,football_state,football_catalog=None):
    """Only the existing canonical ClubSearch adapter can approve this read."""
    if not data or not football_state:return False
    try:
        from .http_framing import split_head
        from .club_inventory import response_for
        from .local_football import FootballStore
        from .local_content import ContentCatalog
        head,body,_=split_head(data);lines=head.split(b'\r\n')
        method,target,version=lines[0].decode('ascii').split()
        headers={l.split(b':',1)[0].lower():l.split(b':',1)[1].strip() for l in lines[1:] if b':' in l}
        headers=checked_session_headers(headers)
        from .club_player_search import PLAYER_TYPES
        kind = parse_qs(urlsplit(target).query).get('type', [])
        if version != 'HTTP/1.1' or len(kind) != 1 or kind[0] not in {*PLAYER_TYPES, 'manager'}:
            return False
        return response_for(method,target,headers,body,FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None)) is not None
    except (ValueError,TypeError,UnicodeError,KeyError,OSError):return False

def validated_squad_request(data,football_state,football_catalog=None,*,read_only=False):
    if not data or not football_state:return False
    try:
        from .http_framing import split_head
        from .local_football import FootballStore
        from .local_content import ContentCatalog
        from .squad_management import selected,response_for as mutation_response
        from .football_protocol import response_for as read_response
        head,body,_=split_head(data);lines=head.split(b'\r\n')
        method,target,version=lines[0].decode('ascii').split()
        if version!='HTTP/1.1' or not target.startswith(('/ut/game/fifaworldmobile/squad','/ut/delete/game/fifaworldmobile/squad/')):return False
        headers={l.split(b':',1)[0].lower():l.split(b':',1)[1].strip() for l in lines[1:] if b':' in l}
        headers=checked_session_headers(headers)
        store=FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None)
        if not selected(store):return False
        if read_only:
            return method=='GET' and read_response(method,target,headers,body,store,squad_by_id=True) is not None
        return mutation_response(method,target,headers,body,store) is not None
    except (ValueError,TypeError,UnicodeError,KeyError,OSError):return False

def market_request(data,football_state):
    """Lab market only: pass a request the configured adapter has an implemented reply for.

    Unimplemented market requests return None there and stay held (captured first).
    """
    if data is None or football_state is None:return False
    from . import market_protocol
    if market_protocol.ACCOUNT is None:return False
    try:
        from .http_framing import split_head
        head,body,_=split_head(data);lines=head.split(b'\r\n')
        method,target,version=lines[0].decode('ascii').split()
        if version!='HTTP/1.1':return False
        headers={l.split(b':',1)[0].lower():l.split(b':',1)[1].strip() for l in lines[1:] if b':' in l}
        headers=checked_session_headers(headers)
        account=Path(football_state).parent
        return market_protocol.response_for(method,target,headers,body,account) is not None
    except (ValueError,TypeError,UnicodeError,KeyError,OSError):return False

def action(control, name, request=None, data=None, football_state=None, football_catalog=None):
    if not control:
        return 'pass'
    config = json.loads(control.read_text())
    exact=config.get('requests',{})
    browse='GET /ut/game/fifaworldmobile/club?type=player&level=any&nation=-1&league=-1&team=-1&count=12&sort=desc'
    if request not in exact and name=='successor' and exact.get(browse)=='pass' and validated_club_filter(data,football_state,football_catalog):return 'pass'
    if request not in exact and name=='successor':
        if exact.get('GET /ut/game/fifaworldmobile/squad/0')=='pass' and validated_squad_request(data,football_state,football_catalog,read_only=True):return 'pass'
        if config.get('squad_management')=='pass' and validated_squad_request(data,football_state,football_catalog):return 'pass'
    if request not in exact and name=='successor' and market_request(data,football_state):return 'pass'
    if (request not in exact and name=='successor' and
        config.get('owned_player_price_limits_eof') is True and
        owned_player_price_query(data,football_state,football_catalog)):
        return 'close'
    if (request not in exact and name=='successor' and
        config.get('unassigned_item_price_limits_eof') is True and
        owned_player_price_query(data,football_state,football_catalog,unassigned=True)):
        return 'close'
    # ACCOMP-001 (1494): ClaimReward carries the reward id in its query; the
    # explicit route key admits every numeric id, nothing else.
    claim = 'GET /victory_fwm_s2/Engine.svc/Challenge/ClaimReward'
    if (request not in exact and request is not None and request.startswith(claim + '?rewardId=')
            and request[len(claim) + 10:].isdigit() and len(request) - len(claim) - 10 <= 10
            and claim in exact):
        return exact[claim]
    # Legacy experiment configs retain successor holds until explicitly enabled.
    fallback=config.get('successor','pass') if name=='inventory' else 'pass'
    value = exact.get(request, config.get(name, fallback))
    if value not in ('pass', 'hold', 'close'):
        raise ValueError('Invalid controlled action')
    return value

def wait_release(control, name, limit=45, request=None, data=None, football_state=None, football_catalog=None):
    # Optional diagnostic hold duration preserves an unanswered control request
    # through a longer observation. No response or client state is generated.
    limits = json.loads(control.read_text()).get('hold_seconds', {})
    limit = limits.get(request, limit)
    if not isinstance(limit, (int, float)) or not 0 < limit <= 180:
        raise ValueError('Invalid bounded transport hold duration')
    start = time.monotonic()
    while action(control, name, request, data, football_state, football_catalog) == 'hold' and time.monotonic() - start < limit:
        time.sleep(0.02)
    result = action(control, name, request, data, football_state, football_catalog)
    return 'close' if result == 'hold' else result
