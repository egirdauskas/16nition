"""Transfer Market wire adapter (MARKET-001..006), configured per process.

Enabled only with an explicit market policy on an archived isolated account, or
on the normal account through a certified release marker (market_release).
Read routes answer from the authoritative market store; state-changing routes
are added only after their genuine request is captured (fail closed).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = None


def configure(account=None, policy=None):
    global ACCOUNT
    from .market_economy import use_policy, POLICY_PATH
    ACCOUNT = None
    if account is None or policy is None:
        use_policy(POLICY_PATH)
        return
    account = Path(account).resolve()
    from . import market_release
    from .fresh_account_runtime import selected as fresh_selected
    if account == market_release.REAL:
        market_release.admit(account, policy)     # certified normal-account admission
    elif not fresh_selected(account) and (ROOT / 'reports' not in account.parents or account.name != 'isolated-account'
            or not (account / '.lab-snapshot.json').is_file()):
        raise ValueError('Uncertified market requires an archived isolated account')
    use_policy(policy)
    ACCOUNT = account


def response_for(method, target, headers, body, account):
    if ACCOUNT is None or account is None or Path(account).resolve() != ACCOUNT:
        return None
    # Finish any prepared settlement, then apply due bot outbids/auction ends
    # (pre-decided at bid time), before a wallet/inventory read is served.
    from .market_settlement import recover
    from .market_bids import apply_due
    from . import market_store as store
    recover(ACCOUNT)
    apply_due(ACCOUNT, store.now())
    from .market_search import ROUTE, response_for as search_reply
    if target.split('?', 1)[0] == ROUTE:
        return search_reply(method, target, headers, body, ACCOUNT)
    if target.split('?', 1)[0] == STATUS:
        return status_reply(method, target, headers, body)
    if target.split('?', 1)[0] == WATCHLIST and method == 'PUT':
        return watch_preview(method, target, headers, body)
    if target.split('?', 1)[0] == WATCHLIST:
        return watchlist_reply(method, target, headers, body)
    if target.split('?', 1)[0] == PRICELIMITS:
        return pricelimits_reply(method, target, headers, body)
    if method == 'POST' and target.startswith(OFFER_PREFIX):
        return offer_preview(method, target, headers, body)
    if target == AUCTIONHOUSE:
        return listing_preview(method, target, headers, body)
    if target.startswith(REMOVE_TRADE):
        return remove_trade_preview(method, target, headers, body)
    if target.split('?', 1)[0] == REMOVE_WATCH:
        return remove_watch_preview(method, target, headers, body)
    if target == ITEM and method == 'PUT':
        return claim_preview(method, target, headers, body)
    return None


STATUS = '/ut/game/fifaworldmobile/trade/status'


def status_reply(method, target, headers, body):
    """1393 genuine: GET trade/status?itemdata=true&tradeIds=<id>[,<id>]."""
    from urllib.parse import parse_qs, urlsplit
    from .game_auth import SID
    from .identity import json_response
    from . import market_store as store

    if (method != 'GET' or body or headers.get(b'host') != b'10.0.2.2:18081'
            or headers.get(b'x-ut-sid') != SID.encode() or headers.get(b'content-length', b'0') != b'0'):
        return None
    query = parse_qs(urlsplit(target).query)
    if set(query) != {'itemdata', 'tradeIds'} or query['itemdata'] != ['true'] or len(query['tradeIds']) != 1:
        return None
    try:
        ids = [int(x) for x in query['tradeIds'][0].split(',')]
    except ValueError:
        return None
    if not ids or len(ids) > 50 or any(str(i) not in query['tradeIds'][0].split(',') for i in ids):
        return None
    at = store.now()
    listings = {l['trade_id']: l for l in store.refresh(ACCOUNT, at)['listings']}
    rows = [store.auction_info(listings[i], at, ACCOUNT) for i in ids if i in listings]
    # 1394: this parser installs the response's `credits` into the native
    # wallet (absent -> 0 shown). Always report the authoritative balance.
    from .local_profile import load_profile
    credits = load_profile(ACCOUNT / 'profile.json').credits
    return json_response({'auctionInfo': rows, 'credits': credits})


WATCHLIST = '/ut/game/fifaworldmobile/watchList'


def watchlist_reply(method, target, headers, body):
    """Genuine GET watchList?offset=0&count=30 (Transfer Targets).

    Parser 01035620 hands the body to the shared auction list reader 0102a320
    (auctionInfo records via 01029c80; optional credits/total), like search.
    """
    from urllib.parse import parse_qs, urlsplit
    from .game_auth import SID
    from .identity import json_response
    from .local_profile import load_profile
    from . import market_store as store

    if (method != 'GET' or body or headers.get(b'host') != b'10.0.2.2:18081'
            or headers.get(b'x-ut-sid') != SID.encode() or headers.get(b'content-length', b'0') != b'0'):
        return None
    query = parse_qs(urlsplit(target).query)
    if set(query) != {'offset', 'count'} or len(query['offset']) != 1 or len(query['count']) != 1:
        return None
    offset, count = query['offset'][0], query['count'][0]
    if not (offset.isdigit() and count.isdigit()) or str(int(offset)) != offset or str(int(count)) != count:
        return None
    if not 1 <= int(count) <= 100:
        return None
    at = store.now()
    rows = store.watchlist(ACCOUNT, at)[int(offset):int(offset) + int(count)]
    credits = load_profile(ACCOUNT / 'profile.json').credits
    return json_response({'auctionInfo': [store.auction_info(l, at, ACCOUNT) for l in rows], 'credits': credits})


def parse_watch(method, target, headers, body):
    """1401 genuine ADD TO WATCH LIST: PUT watchList?tradeId=<id> {"auctionInfo":[{"id":<id>}]}.

    FutISWatchTrade has no JSON reader call in its block (0103571c..01035cd0);
    the reply is an empty object with HTTP 200, like RemoveTrade.
    """
    import json
    from urllib.parse import parse_qs, urlsplit
    from .game_auth import SID

    if (method != 'PUT' or headers.get(b'host') != b'10.0.2.2:18081' or headers.get(b'x-ut-sid') != SID.encode()
            or headers.get(b'content-type') != b'application/json'
            or headers.get(b'content-length') != str(len(body)).encode()):
        return None
    query = parse_qs(urlsplit(target).query)
    if set(query) != {'tradeId'} or len(query['tradeId']) != 1:
        return None
    text = query['tradeId'][0]
    if not text.isdigit() or str(int(text)) != text:
        return None
    try:
        value = json.loads(body)
    except ValueError:
        return None
    if value != {'auctionInfo': [{'id': int(text)}]}:
        return None
    return int(text)


def watch_preview(method, target, headers, body):
    from .identity import json_response
    from . import market_store as store

    trade_id = parse_watch(method, target, headers, body)
    if trade_id is None:
        return None
    listing = next((l for l in store.load(ACCOUNT)['listings'] if l['trade_id'] == trade_id), None)
    if listing is None or listing['seller'] != 'bot':
        return None
    return json_response({})


PRICELIMITS = '/ut/game/fifaworldmobile/marketdata/item/pricelimits'


def pricelimits_reply(method, target, headers, body):
    """Genuine GET marketdata/item/pricelimits?itemIdList=<owned id>[,...].

    Parser 01035d80 reads a top-level array of records with keys 0xe1 itemId,
    0x120 minPrice and 0x11e maxPrice (64-bit each; key table 02884fe8).
    """
    from urllib.parse import parse_qs, urlsplit
    from .game_auth import SID
    from .identity import json_response
    from .local_content import ContentCatalog
    from .local_football import FootballStore
    from . import market_economy as economy

    if (method != 'GET' or body or headers.get(b'host') != b'10.0.2.2:18081'
            or headers.get(b'x-ut-sid') != SID.encode() or headers.get(b'content-length', b'0') != b'0'):
        return None
    query = parse_qs(urlsplit(target).query)
    if set(query) != {'itemIdList'} or len(query['itemIdList']) != 1:
        return None
    parts = query['itemIdList'][0].split(',')
    if not 1 <= len(parts) <= 50 or any(not p.isdigit() or str(int(p)) != p for p in parts):
        return None
    football = FootballStore(ACCOUNT / 'football.json', ContentCatalog(ACCOUNT / 'content.json')).load(1)
    from .local_football import owned_instance_ids
    from .market_items import owned_entry, tradeable
    owned = {i.instance_id: i for i in football.owned_items}
    known = owned_instance_ids(football)
    rows = []
    for part in parts:
        item = owned.get(int(part))
        if item is None and int(part) in known:
            # Policy v1: tradeable items get their own range; others get no record.
            kind, entry = owned_entry(football, int(part))
            if kind is None or not economy.items_enabled():
                continue
            try:
                card = tradeable(kind, entry)
            except ValueError:
                continue
            rows.append({'itemId': int(part), 'minPrice': economy.card_minimum(card),
                         'maxPrice': economy.card_maximum(card)})
            continue
        if item is None:
            return None        # unknown ids hold the whole request
        card = economy.facts(item.resource_id, item.special_version_id)
        rows.append({'itemId': item.instance_id, 'minPrice': economy.card_minimum(card),
                     'maxPrice': economy.card_maximum(card)})
    return json_response(rows)


OFFER_PREFIX = '/ut/game/fifaworldmobile/trade/'


def parse_offer(method, target, headers, body):
    """1395 genuine Buy Now: POST trade/<id>/offer {"bid":<buyNow>,"itemData":[]}."""
    import json
    from .game_auth import SID

    if (method != 'POST' or not target.startswith(OFFER_PREFIX) or not target.endswith('/offer')
            or headers.get(b'host') != b'10.0.2.2:18081' or headers.get(b'x-ut-sid') != SID.encode()
            or headers.get(b'content-type') != b'application/json'
            or headers.get(b'content-length') != str(len(body)).encode()):
        return None
    middle = target[len(OFFER_PREFIX):-len('/offer')]
    if not middle.isdigit() or str(int(middle)) != middle:
        return None
    try:
        value = json.loads(body)
    except ValueError:
        return None
    if (type(value) is not dict or set(value) != {'bid', 'itemData'} or value['itemData'] != []
            or type(value['bid']) is not int or value['bid'] <= 0):
        return None
    return int(middle), value['bid']


def offer_preview(method, target, headers, body):
    """Reply a Buy Now would produce, without writes; None = held/unmapped."""
    from .identity import json_response
    from .local_profile import load_profile
    from . import market_store as store
    from . import market_settlement as settle

    parsed = parse_offer(method, target, headers, body)
    if parsed is None:
        return None
    trade_id, bid = parsed
    settle.recover(ACCOUNT)
    listing = next((l for l in store.load(ACCOUNT)['listings'] if l['trade_id'] == trade_id), None)
    if listing is None:
        return None
    receipt = listing.get('settlement')
    if receipt is not None:
        return json_response({'credits': receipt['credits_after']}) if receipt['price'] == bid else None
    credits = load_profile(ACCOUNT / 'profile.json').credits
    if bid != listing['buy_now']:
        # 1397 genuine auction bid: same route and reply contract as Buy Now.
        from .market_bids import plan_bid
        try:
            receipt, _ = plan_bid(store.load(ACCOUNT), credits, trade_id, bid, store.now())
        except ValueError:
            return None
        return json_response({'credits': receipt['credits_after']})
    if listing['state'] != 'active' or listing['seller'] != 'bot' or listing['expires_at'] <= store.now():
        return None
    if credits < bid:
        return None
    return json_response({'credits': credits - bid})


AUCTIONHOUSE = '/ut/game/fifaworldmobile/auctionhouse'
def parse_listing(method, target, headers, body):
    """1397 genuine: POST auctionhouse {"itemData":{"id":N},"startingBid":S,"buyNowPrice":B,"duration":D}."""
    import json
    from .game_auth import SID

    if (method != 'POST' or target != AUCTIONHOUSE
            or headers.get(b'host') != b'10.0.2.2:18081' or headers.get(b'x-ut-sid') != SID.encode()
            or headers.get(b'content-type') != b'application/json'
            or headers.get(b'content-length') != str(len(body)).encode()):
        return None
    try:
        value = json.loads(body)
    except ValueError:
        return None
    if type(value) is not dict or set(value) != {'itemData', 'startingBid', 'buyNowPrice', 'duration'}:
        return None
    item = value['itemData']
    if type(item) is not dict or set(item) != {'id'} or type(item['id']) is not int or item['id'] <= 0:
        return None
    numbers = (value['startingBid'], value['buyNowPrice'], value['duration'])
    if any(type(n) is not int or n <= 0 for n in numbers):
        return None
    return item['id'], value['startingBid'], value['buyNowPrice'], value['duration']


def listing_preview(method, target, headers, body):
    """Reply a listing would produce, without writes: 023093c8 reads only `id`."""
    from .identity import json_response
    from .local_content import ContentCatalog
    from .local_football import FootballStore
    from .market_listings import plan_listing
    from . import market_store as store

    parsed = parse_listing(method, target, headers, body)
    if parsed is None:
        return None
    football = FootballStore(ACCOUNT / 'football.json', ContentCatalog(ACCOUNT / 'content.json')).load(1)
    try:
        receipt, _ = plan_listing(store.load(ACCOUNT), football, *parsed, store.now())
    except ValueError:
        return None
    return json_response({'id': receipt['trade_id']})


REMOVE_TRADE = '/ut/delete/game/fifaworldmobile/trade/'


def parse_remove_trade(method, target, headers, body):
    """1400 genuine CLEAR SOLD ITEMS: GET /ut/delete/game/fifaworldmobile/trade/<tradeId>.

    FutISRemoveTrade has no dedicated body parser located (its call VT+8
    01056708 only requires HTTP 200); the reply is an empty JSON object.
    """
    from .game_auth import SID

    if (method != 'GET' or body or not target.startswith(REMOVE_TRADE)
            or headers.get(b'host') != b'10.0.2.2:18081' or headers.get(b'x-ut-sid') != SID.encode()
            or headers.get(b'content-length', b'0') != b'0'):
        return None
    tail = target[len(REMOVE_TRADE):]
    if not tail.isdigit() or str(int(tail)) != tail:
        return None
    return int(tail)


def remove_trade_preview(method, target, headers, body):
    from .identity import json_response
    from .market_listings import plan_clear_sold
    from . import market_store as store

    trade_id = parse_remove_trade(method, target, headers, body)
    if trade_id is None:
        return None
    try:
        plan_clear_sold(store.load(ACCOUNT), trade_id)
    except ValueError:
        return None
    return json_response({})


REMOVE_WATCH = '/ut/delete/game/fifaworldmobile/watchList'
ITEM = '/ut/game/fifaworldmobile/item'


def parse_remove_watch(method, target, headers, body):
    """1402 genuine Claim/Clear (lost row): GET ut/delete/.../watchList?tradeId=<id>[,<id>].

    FutISRemoveWatch has no JSON reader in its block (01035000..01035448); reply {}.
    """
    from urllib.parse import parse_qs, urlsplit
    from .game_auth import SID

    if (method != 'GET' or body or headers.get(b'host') != b'10.0.2.2:18081'
            or headers.get(b'x-ut-sid') != SID.encode() or headers.get(b'content-length', b'0') != b'0'):
        return None
    query = parse_qs(urlsplit(target).query)
    if set(query) != {'tradeId'} or len(query['tradeId']) != 1:
        return None
    parts = query['tradeId'][0].split(',')
    if not 1 <= len(parts) <= 50 or any(not p.isdigit() or str(int(p)) != p for p in parts):
        return None
    return [int(p) for p in parts]


def removable(listing):
    """A Transfer Targets row the player may drop: not a live auction they lead."""
    if listing['seller'] != 'bot' or not (listing.get('watched') or listing.get('player_bids')):
        return False
    return not (listing['state'] == 'active' and listing.get('high_bidder') == 'player')


def remove_watch_preview(method, target, headers, body):
    from .identity import json_response
    from . import market_store as store

    trades = parse_remove_watch(method, target, headers, body)
    if trades is None:
        return None
    listings = {l['trade_id']: l for l in store.load(ACCOUNT)['listings']}
    if any(t not in listings or not removable(listings[t]) for t in trades):
        return None
    return json_response({})


def parse_claim(method, target, headers, body):
    """1402 genuine Claim/Clear (won row): PUT item {"itemData":[{"id","pile":"purchased","swap":0,"tradeId":0}]}."""
    import json
    from .game_auth import SID

    if (method != 'PUT' or target != ITEM or headers.get(b'host') != b'10.0.2.2:18081'
            or headers.get(b'x-ut-sid') != SID.encode() or headers.get(b'content-type') != b'application/json'
            or headers.get(b'content-length') != str(len(body)).encode()):
        return None
    try:
        value = json.loads(body)
    except ValueError:
        return None
    if type(value) is not dict or set(value) != {'itemData'} or type(value['itemData']) is not list:
        return None
    ids = []
    for row in value['itemData']:
        if (type(row) is not dict or row.get('pile') != 'purchased' or row.get('swap') != 0
                or row.get('tradeId') != 0 or set(row) != {'id', 'pile', 'swap', 'tradeId'}
                or type(row['id']) is not int):
            return None
        ids.append(row['id'])
    if not ids or len(set(ids)) != len(ids):
        return None
    return ids


def won_listings(market, instance_ids):
    """Won auctions for these owned instances, or None if any is not a won card."""
    rows = []
    for instance in instance_ids:
        listing = next((l for l in market['listings'] if l['seller'] == 'bot'
                        and (l.get('settlement') or {}).get('instance_id') == instance
                        and l['settlement'].get('buyer') == 'player' and l.get('player_bids')), None)
        if listing is None:
            return None
        rows.append(listing)
    return rows


def claim_preview(method, target, headers, body):
    from .identity import json_response
    from .local_content import ContentCatalog
    from .local_football import FootballStore, item_pile
    from . import market_store as store

    ids = parse_claim(method, target, headers, body)
    if ids is None or won_listings(store.load(ACCOUNT), ids) is None:
        return None
    football = FootballStore(ACCOUNT / 'football.json', ContentCatalog(ACCOUNT / 'content.json')).load(1)
    if any(item_pile(football, i) != 'unassigned' for i in ids):
        return None
    return json_response({'itemData': [{'id': i, 'pile': 'purchased', 'success': True} for i in ids]})


def items_tradeable(account, football, instance_id):
    """True when the configured v1 market lets this owned non-player card be listed."""
    if ACCOUNT is None or account is None or Path(account).resolve() != ACCOUNT:
        return False
    from . import market_economy as economy
    from .market_items import owned_entry, tradeable
    if not economy.items_enabled():
        return False
    kind, owned = owned_entry(football, instance_id)
    if kind in (None, 'player'):
        return False
    if kind == 'manager' and manager_in_use(football, instance_id):
        return False
    try:
        tradeable(kind, owned)
    except ValueError:
        return False
    return True


def manager_in_use(football, instance_id):
    """The active manager, or one named by any saved squad."""
    from .local_squads import records
    if football.active_manager is not None and football.active_manager.instance_id == instance_id:
        return True
    return any(r.manager_id == instance_id for r in records(football))


def escrowed(account):
    """Instance IDs held by active listings (empty when the market is off)."""
    if ACCOUNT is None or account is None or Path(account).resolve() != ACCOUNT:
        return set()
    from .market_listings import listed_instance_ids
    from . import market_store as store
    if not (ACCOUNT / store.NAME).exists():
        return set()
    return listed_instance_ids(store.load(ACCOUNT))


def tradepile_rows(account, rows):
    """Replace inactive Transfer List rows by their listing state; add uncleared sold rows."""
    if ACCOUNT is None or account is None or Path(account).resolve() != ACCOUNT:
        return rows
    from .market_listings import current_listing
    from . import market_store as store
    if not (ACCOUNT / store.NAME).exists():
        return rows
    at = store.now()
    market = store.load(ACCOUNT)
    out = []
    for row in rows:
        listing = current_listing(market, row['itemData']['id'])
        if listing is None or listing['state'] == 'closed' or listing.get('reclaimed'):
            out.append(row)
        else:
            out.append(store.auction_info(listing, at, ACCOUNT))
    for listing in market['listings']:
        if (listing['seller'] == 'player' and listing['state'] == 'closed'
                and not listing.get('sold_cleared')):
            out.append(store.auction_info(listing, at, ACCOUNT))
    return out


def commit_request(method, target, headers, body, account):
    from .identity import json_response
    from . import market_settlement as settle

    if ACCOUNT is None or account is None or Path(account).resolve() != ACCOUNT:
        return None
    removed_watch = parse_remove_watch(method, target, headers, body) if target.startswith(REMOVE_WATCH) else None
    if removed_watch is not None:
        from . import market_store as store
        reply = remove_watch_preview(method, target, headers, body)
        if reply is None:
            return None
        for trade_id in removed_watch:
            store.set_watch(ACCOUNT, trade_id, False)
        return reply
    claimed = parse_claim(method, target, headers, body)
    if claimed is not None:
        from . import market_store as store
        reply = claim_preview(method, target, headers, body)
        if reply is None:
            return None
        for listing in won_listings(store.load(ACCOUNT), claimed):
            store.set_watch(ACCOUNT, listing['trade_id'], False)
        return reply
    watched = parse_watch(method, target, headers, body)
    if watched is not None:
        from . import market_store as store
        store.set_watch(ACCOUNT, watched, True)
        return json_response({})
    removed = parse_remove_trade(method, target, headers, body)
    if removed is not None:
        from .market_listings import clear_sold
        clear_sold(ACCOUNT, removed)
        return json_response({})
    listing = parse_listing(method, target, headers, body)
    if listing is not None:
        from .market_listings import list_item
        from . import market_store as store
        receipt = list_item(ACCOUNT, *listing, store.now())
        return json_response({'id': receipt['trade_id']})
    parsed = parse_offer(method, target, headers, body)
    if parsed is None:
        return None
    from . import market_store as store
    trade_id, bid = parsed
    listing = next((l for l in store.load(ACCOUNT)['listings'] if l['trade_id'] == trade_id), None)
    if listing is not None and listing.get('settlement') is None and bid != listing['buy_now']:
        from .market_bids import place_bid
        receipt = place_bid(ACCOUNT, trade_id, bid, store.now())
        return json_response({'credits': receipt['credits_after']})
    receipt = settle.buy_now(ACCOUNT, trade_id, bid, store.now())
    return json_response({'credits': receipt['credits_after']})


HUB = '/ut/game/fifaworldmobile/hub'


def hub_response(method, target, headers, body, account):
    """GetHubData (route 0x5a): genuine GET /ut/game/fifaworldmobile/hub, empty body.

    Isolated probe 1461 proved the Transfers-hub tile "SEARCH TRANSFER MARKET —
    N Live Items" reads `auctionCount` from this reply (it was always closed
    before, so the tile showed 0). Reply with the listings currently live on the
    local Market. Read-only apart from the existing lazy refresh.
    """
    from .game_auth import SID
    from .identity import json_response
    from . import market_store as store

    if ACCOUNT is None or account is None or Path(account).resolve() != ACCOUNT:
        return None
    if (method != 'GET' or target != HUB or body or headers.get(b'host') != b'10.0.2.2:18081'
            or headers.get(b'x-ut-sid') != SID.encode() or headers.get(b'content-length', b'0') != b'0'):
        return None
    at = store.now()
    listings = store.refresh(ACCOUNT, at)['listings']
    live = sum(1 for l in listings if l['state'] == 'active' and l['expires_at'] > at)
    return json_response({'auctionCount': live})
