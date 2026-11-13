"""Offline Transfer Market store (MARKET-002/006): authoritative listings.

One account-local journal `market.json` owns every listing. Bot listings are
generated from supplied catalog cards with seeded draws (market_economy), persisted
before they are ever shown, and never regenerated: identities are trade IDs from
a monotone counter. Bot item IDs live in a reserved range that can never collide
with owned instance IDs. All writes are whole-file atomic under ACCOUNT_LOCK.
"""

import copy
import json
import time
from pathlib import Path

from . import market_economy as economy
from .account_transaction import account_locked, atomic

NAME = 'market.json'
VERSION = 'market_store_v1'
BOT_ITEM_BASE = 0x4000000000000000   # reserved; owned IDs stay far below
FIRST_TRADE_ID = 7_000_000_001


def now():
    return int(time.time())


def empty():
    return {'version': VERSION, 'next_trade_id': FIRST_TRADE_ID, 'listings': []}


def load(account):
    path = Path(account) / NAME
    if not path.exists():
        return empty()
    value = json.loads(path.read_bytes())
    if value.get('version') != VERSION or set(value) != {'version', 'next_trade_id', 'listings'}:
        raise ValueError('Unknown market store')
    ids = [listing['trade_id'] for listing in value['listings']]
    if len(ids) != len(set(ids)) or any(i >= value['next_trade_id'] for i in ids):
        raise ValueError('Market trade identity conflict')
    return value


def save(account, value):
    atomic(Path(account) / NAME, (json.dumps(value, indent=2, sort_keys=True) + '\n').encode())


# --- Bot supply -------------------------------------------------------------

def _pools():
    from .card_pool import card_index
    from .reconstructed_specials import reviewed_pool

    pools = {'bronze': [], 'silver': [], 'gold': [], 'gold_elite': [], 'special': []}
    elite = economy.load_policy()['demand']['elite_rating']
    for card in card_index().values():
        if not card.lookup_supported or card.variant_bits:
            continue
        name = 'gold_elite' if card.quality == 'gold' and card.rating >= elite else card.quality
        if name in pools:
            pools[name].append((card.resource_id, None))
    for special in reviewed_pool():
        pools["special"].append((special.base_resource_id, special.record_id))
    return {name: sorted(rows) for name, rows in pools.items()}


_POOL_CACHE = []


def pools():
    if not _POOL_CACHE:
        _POOL_CACHE.append(_pools())
    return _POOL_CACHE[0]


def generate_bot_listing(trade_id, created_at, big_five=False):
    """One bot listing from supplied cards; deterministic for its trade ID.

    ``big_five`` (market_supply_big5, selected per account) doubles the
    big-five-league share of the gold tiers for newly generated listings.
    """
    policy = economy.load_policy()
    supply = policy['supply']
    draw = economy.rng('supply', trade_id)
    tier_pools = pools()
    tier_weights = supply['weights']
    if big_five:
        from . import market_supply_big5
        tier_weights, _ = market_supply_big5.weights(supply['weights'], tier_pools)
        tier_pools = market_supply_big5.split_pools(tier_pools)
    names = sorted(tier_weights)
    tier = draw.choices(names, weights=[tier_weights[n] for n in names])[0]
    resource_id, special = draw.choice(tier_pools[tier])
    card = economy.facts(resource_id, special)
    start, buy_now = economy.bot_listing_price(trade_id, card, policy)
    lengths = sorted(supply['duration_weights'], key=int)
    duration = int(draw.choices(lengths, weights=[supply['duration_weights'][n] for n in lengths])[0])
    return {
        'trade_id': trade_id, 'seller': 'bot',
        'item': {
            'id': BOT_ITEM_BASE + trade_id, 'resource_id': resource_id,
            'special_version_id': special, 'formation_id': bot_formation(trade_id),
        },
        'starting_bid': start, 'buy_now': buy_now, 'current_bid': 0, 'high_bidder': None,
        'created_at': created_at, 'expires_at': created_at + duration, 'state': 'active',
    }


def generate_item_listing(trade_id, created_at, category):
    """One bot item listing for a stock search category (ball/stadium/clubInfo/staff)."""
    from .market_items import supply_pool
    policy = economy.load_policy()
    rule = policy['items']['supply']
    draw = economy.rng('supply-item', category, trade_id)
    pool = supply_pool(category)
    if category == 'clubInfo':
        kind = 'kit' if draw.random() * 100 < rule['kit_percent'] else 'badge'
        pool = [entry for entry in pool if entry[0] == kind]
    kind, resource_id = draw.choice(pool)
    card = economy.item_facts(kind, resource_id)
    start, buy_now = economy.bot_listing_price(f'item:{trade_id}', card, policy)
    lengths = sorted(policy['supply']['duration_weights'], key=int)
    duration = int(draw.choices(lengths, weights=[policy['supply']['duration_weights'][n] for n in lengths])[0])
    return {
        'trade_id': trade_id, 'seller': 'bot', 'category': category,
        'item': {'id': BOT_ITEM_BASE + trade_id, 'kind': kind, 'resource_id': resource_id},
        'starting_bid': start, 'buy_now': buy_now, 'current_bid': 0, 'high_bidder': None,
        'created_at': created_at, 'expires_at': created_at + duration, 'state': 'active',
    }


def item_formation(listing):
    """The listing card's formation; bot listings made before formations were
    stored use the same seeded draw (a missing formation renders as UNDEFINED)."""
    formation = listing['item'].get('formation_id')
    if formation is None and listing['seller'] == 'bot' and 'kind' not in listing['item']:
        return bot_formation(listing['trade_id'])
    return formation


def bot_formation(trade_id):
    """Revival policy: uniform over the 17 original-client formations.

    Own seeded stream, so adding it leaves every other listing draw unchanged.
    """
    from .local_formations import FORMATIONS
    return economy.rng('formation', trade_id).choice(sorted(FORMATIONS))


@account_locked
def refresh(account, at=None):
    """Expire past listings and top bot supply up to the configured size."""
    at = now() if at is None else at
    value = load(account)
    before = copy.deepcopy(value)
    for listing in value['listings']:
        # Player listings and auctions the player bid on end through
        # market_bids.apply_due (sale/settlement), never by plain expiry here.
        if listing.get('player_bids') or listing['seller'] == 'player':
            continue
        if listing['state'] == 'active' and listing['expires_at'] <= at:
            listing['state'] = 'expired'
    policy = economy.load_policy()
    from . import market_supply_big5
    big_five = market_supply_big5.enabled(account)
    sizes = {None: policy['supply']['inventory_size']}
    if big_five:
        sizes[None] = market_supply_big5.inventory_size(
            policy['supply']['inventory_size'], policy['supply']['weights'], pools())
    if economy.items_enabled(policy):
        sizes.update((k, v) for k, v in policy['items']['supply'].items() if k in ('ball', 'stadium', 'clubInfo', 'staff'))
    from . import market_supply_scale
    sizes = market_supply_scale.scaled(sizes, account)
    for category, size in sizes.items():
        active = sum(1 for l in value['listings']
                     if l['seller'] == 'bot' and l['state'] == 'active' and l.get('category') == category)
        while active < size:
            trade_id = value['next_trade_id']
            value['next_trade_id'] += 1
            if category is None:
                value['listings'].append(generate_bot_listing(trade_id, at, big_five))
            else:
                value['listings'].append(generate_item_listing(trade_id, at, category))
            active += 1
    # Bounded history: drop finished bot listings nobody can reference any more.
    # 1396: a settled trade must stay readable (trade/status after Buy Now; an
    # empty reply crashed the client) and keeps its retry receipt forever.
    value['listings'] = [l for l in value['listings']
                         if l['state'] == 'active' or l['seller'] != 'bot' or l.get('high_bidder')
                         or l.get('settlement') or l.get('player_bids')]
    if value != before:
        save(account, value)
    return value


# --- Search ----------------------------------------------------------------

def auction_info(listing, at, account):
    """Native auctionInfo record (reader 01029c80 keys)."""
    from .football_protocol import encode_item
    from .local_content import ContentCatalog
    from .local_football import FootballStore, OwnedPlayerItem

    item = listing['item']
    settlement = listing.get('settlement') or {}
    # After the player's Buy Now the card is the player's new owned instance.
    item_id = settlement.get('instance_id', item['id'])
    if 'kind' in item:
        from .market_items import encode
        return record(listing, encode(item, item_id, account), at)
    owned = OwnedPlayerItem(
        item_id,
        item['resource_id'],
        formation_id=item_formation(listing),
        special_version_id=item['special_version_id'],
        preferred_position=item.get('preferred_position'),
        training_resource_id=item.get('training_resource_id'),
        injury_type=item.get('injury_type'),
        injury_games=item.get('injury_games'),
    )
    catalog = ContentCatalog(Path(account) / 'content.json')
    if listing['seller'] == 'player' and listing['state'] != 'closed':
        # Existing listings predate the complete snapshot. Their escrowed card
        # is still authoritative; read it without migrating old receipts.
        football = FootballStore(Path(account) / 'football.json', catalog).load(1)
        current = next(
            (card for card in football.owned_items if card.instance_id == item_id),
            None,
        )
        if current is not None:
            if (
                current.resource_id != item['resource_id']
                or current.special_version_id != item['special_version_id']
            ):
                raise ValueError('Listed player ownership identity differs')
            owned = current
    return record(listing, encode_item(owned, catalog, True), at)


def record(listing, data, at):
    """The auctionInfo fields around an encoded itemData."""
    remaining = listing['expires_at'] - at
    return {
        'tradeId': listing['trade_id'], 'itemData': data,
        'tradeState': ('closed' if listing['state'] == 'closed'
                       else 'active' if listing['state'] == 'active' and remaining > 0 else 'expired'),
        'buyNowPrice': listing['buy_now'],
        'currentBid': (listing.get('settlement') or {}).get('price', listing['current_bid']),
        # MARKET-007 (1441): a closed trade reports no time left; with a positive
        # value the stock search row kept its timer and Buy Now after a purchase.
        'startingBid': listing['starting_bid'],
        'expires': -1 if listing['state'] == 'closed' else max(remaining, -1),
        'bidState': bid_state(listing),
        'offers': 0, 'watched': bool(listing.get('watched')),
        'sellerName': 'FIFA Market', 'sellerEstablished': 0,
    }


def watchlist(account, at=None):
    """Transfer Targets: listings the player bid on or watches, not yet removed."""
    at = now() if at is None else at
    value = refresh(account, at)
    rows = [l for l in value['listings']
            if (l.get('player_bids') or l.get('watched')) and not l.get('watch_removed')]
    # Live auctions first (soonest ending), then finished ones.
    rows.sort(key=lambda l: (l['state'] != 'active', l['expires_at'], l['trade_id']))
    return rows


@account_locked
def set_watch(account, trade_id, watched):
    """Add a bot listing to (or remove it from) Transfer Targets; idempotent."""
    value = load(account)
    listing = next((l for l in value['listings'] if l['trade_id'] == trade_id), None)
    if listing is None or listing['seller'] != 'bot':
        raise ValueError('Unknown trade')
    before = (bool(listing.get('watched')), bool(listing.get('watch_removed')))
    if watched:
        listing['watched'] = True
        listing.pop('watch_removed', None)
    else:
        listing['watch_removed'] = True
    if before != (bool(listing.get('watched')), bool(listing.get('watch_removed'))):
        save(account, value)


def bid_state(listing):
    """Native bidState (enum 010308fc: none/highest/outbid/buyNow) for the player."""
    if listing.get('player_bids'):
        return 'highest' if listing.get('high_bidder') == 'player' else 'outbid'
    if (listing.get('settlement') or {}).get('buyer') == 'player':
        return 'buyNow'
    return 'none'


def search(account, query, at=None):
    """Active bot listings matching a decoded query, soonest-expiring first."""
    at = now() if at is None else at
    if query.item_type != 'player' and not query.item_supply():
        return {'auctionInfo': []}
    value = refresh(account, at)
    category = None if query.item_type == 'player' else query.item_type
    rows = []
    for listing in value['listings']:
        if listing['state'] != 'active' or listing['seller'] != 'bot' or listing.get('category') != category:
            continue
        if not query.matches(listing):
            continue
        rows.append(listing)
    rows.sort(key=lambda l: (l['expires_at'], l['trade_id']))
    page = rows[query.start:query.start + query.num]
    return {'auctionInfo': [auction_info(l, at, account) for l in page]}


# --- Player listings and bot buyers (design §3; wiring awaits capture) -------

def player_listing(trade_id, owned, starting_bid, buy_now, duration, created_at):
    """Escrowed player listing with its bot outcome decided once, at creation."""
    card = economy.facts(owned['resource_id'], owned.get('special_version_id'))
    asking = buy_now or starting_bid
    sale_after = economy.schedule_sale(trade_id, card, asking, duration)
    return {
        'trade_id': trade_id, 'seller': 'player',
        'item': {'id': owned['instance_id'], 'resource_id': owned['resource_id'],
                 'special_version_id': owned.get('special_version_id')},
        'starting_bid': starting_bid, 'buy_now': buy_now, 'current_bid': 0, 'high_bidder': None,
        'created_at': created_at, 'expires_at': created_at + duration, 'state': 'active',
        'bot_sale_at': None if sale_after is None else created_at + sale_after,
    }


def seller_listing(trade_id, item, card, starting_bid, buy_now, duration, created_at):
    """Escrowed item listing (policy v1); its bot outcome is decided once, at creation."""
    sale_after = economy.schedule_sale(trade_id, card, buy_now or starting_bid, duration)
    return {
        'trade_id': trade_id, 'seller': 'player', 'item': item,
        'starting_bid': starting_bid, 'buy_now': buy_now, 'current_bid': 0, 'high_bidder': None,
        'created_at': created_at, 'expires_at': created_at + duration, 'state': 'active',
        'bot_sale_at': None if sale_after is None else created_at + sale_after,
    }


def due_bot_sale(listing, at):
    """True when a scheduled bot buyer acts against the listing's current state."""
    return (listing['seller'] == 'player' and listing['state'] == 'active'
            and listing.get('bot_sale_at') is not None and listing['bot_sale_at'] <= at
            and listing['bot_sale_at'] < listing['expires_at'])
