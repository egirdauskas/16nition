"""Player listings on the Transfer List (MARKET-003/006).

Genuine request (1397): POST auctionhouse
{"itemData":{"id":<owned>},"startingBid":S,"buyNowPrice":B,"duration":D}.
Reply parser 023093c8 (FutISStartServerResponse) reads only key 0xd6 `id`,
the new 64-bit trade ID; it returns success unconditionally.

Custody: the card stays in the `trade` pile (escrow) while its listing is
active; moves/quick sell of a listed card are refused. Whether a bot buys, and
when, is decided once at listing time (market_store.player_listing); the sale
is applied lazily by market_bids.apply_due. A bot pays the Buy Now price (or
the starting bid without one); the player receives it minus the policy fee and
the card leaves the club for good. Unsold listings expire back to the
Transfer List.
"""

import copy
import json
from pathlib import Path

from . import market_economy as economy
from . import market_store
from .account_transaction import account_locked
from .market_settlement import commit, encode, recover


def listed_instance_ids(market):
    """Owned instance IDs held by an active player listing (escrow)."""
    return {
        l['item']['id'] for l in market['listings']
        if l['seller'] == 'player' and l['state'] == 'active'
    }


def current_listing(market, instance_id):
    """The player's most recent listing for this instance, if any."""
    rows = [l for l in market['listings'] if l['seller'] == 'player' and l['item']['id'] == instance_id]
    return max(rows, key=lambda l: l['trade_id']) if rows else None


def plan_listing(market, football, instance_id, starting_bid, buy_now, duration, at, policy=None):
    """(receipt, updated market) for a valid listing; ValueError otherwise. No writes."""
    from .local_football import item_pile

    policy = policy or economy.load_policy()
    existing = current_listing(market, instance_id)
    if (existing is not None and existing['state'] == 'active' and existing['starting_bid'] == starting_bid
            and existing['buy_now'] == buy_now and existing['expires_at'] - existing['created_at'] == duration):
        return existing['receipt'], market          # exact retry
    if instance_id in listed_instance_ids(market):
        raise ValueError('Already listed')
    from .market_items import owned_entry
    kind, _ = owned_entry(football, instance_id)
    if kind not in (None, 'player'):
        return plan_item_listing(market, football, instance_id, starting_bid, buy_now, duration, at, policy)
    item = next((i for i in football.owned_items if i.instance_id == instance_id), None)
    if item is None or item_pile(football, instance_id) != 'trade':
        raise ValueError('Only owned Transfer List players can be listed')
    if instance_id in football.untradeable_instance_ids:
        raise ValueError('Untradeable item')
    if duration not in policy['listing']['durations_seconds']:
        raise ValueError('Unsupported duration')
    card = economy.facts(item.resource_id, item.special_version_id)
    low = economy.card_minimum(card, policy)
    high = economy.card_maximum(card, policy)
    for price in (starting_bid, buy_now):
        if price != economy.round_price(price, policy) or not low <= price <= high:
            raise ValueError('Price outside the card range')
    if buy_now < starting_bid:
        raise ValueError('Buy Now below starting bid')
    trade_id = market['next_trade_id']
    owned = {'instance_id': instance_id, 'resource_id': item.resource_id,
             'special_version_id': item.special_version_id}
    listing = market_store.player_listing(trade_id, owned, starting_bid, buy_now, duration, at)
    listing['item']['formation_id'] = item.formation_id
    # Keep owned overrides with the auction, including its sold display after
    # ownership is retired. Reconstructing only the base resource loses an
    # applied position card, training and injury information in the stock UI.
    for name in ('preferred_position', 'training_resource_id', 'injury_type', 'injury_games'):
        value = getattr(item, name)
        if value is not None:
            listing['item'][name] = value
    receipt = {'trade_id': trade_id, 'instance_id': instance_id, 'at': at}
    listing['receipt'] = receipt
    after = copy.deepcopy(market)
    after['next_trade_id'] += 1
    after['listings'].append(listing)
    return receipt, after


def plan_item_listing(market, football, instance_id, starting_bid, buy_now, duration, at, policy):
    """Listing of a consumable, club item or spare manager (policy v1 only)."""
    from .local_football import item_pile
    from .market_items import owned_entry, snapshot, tradeable
    from .market_protocol import manager_in_use

    if not economy.items_enabled(policy):
        raise ValueError('Item trading needs market policy v1')
    kind, owned = owned_entry(football, instance_id)
    if item_pile(football, instance_id) != 'trade':
        raise ValueError('Only Transfer List items can be listed')
    if instance_id in football.untradeable_instance_ids:
        raise ValueError('Untradeable item')
    if kind == 'manager' and manager_in_use(football, instance_id):
        raise ValueError('Manager is used by a squad')
    if duration not in policy['listing']['durations_seconds']:
        raise ValueError('Unsupported duration')
    card = tradeable(kind, owned)
    low = economy.card_minimum(card, policy)
    high = economy.card_maximum(card, policy)
    for price in (starting_bid, buy_now):
        if price != economy.round_price(price, policy) or not low <= price <= high:
            raise ValueError('Price outside the item range')
    if buy_now < starting_bid:
        raise ValueError('Buy Now below starting bid')
    trade_id = market['next_trade_id']
    listing = market_store.seller_listing(trade_id, snapshot(kind, owned), card, starting_bid, buy_now,
                                          duration, at)
    receipt = {'trade_id': trade_id, 'instance_id': instance_id, 'at': at}
    listing['receipt'] = receipt
    after = copy.deepcopy(market)
    after['next_trade_id'] += 1
    after['listings'].append(listing)
    return receipt, after


@account_locked
def list_item(account, instance_id, starting_bid, buy_now, duration, at):
    from .local_content import ContentCatalog
    from .local_football import FootballStore
    from .market_bids import apply_due

    account = Path(account)
    apply_due(account, at)
    if not (account / market_store.NAME).exists():
        market_store.refresh(account, at)
    raw = {market_store.NAME: (account / market_store.NAME).read_bytes()}
    market = market_store.load(account)
    football = FootballStore(account / 'football.json', ContentCatalog(account / 'content.json')).load(1)
    receipt, after = plan_listing(market, football, instance_id, starting_bid, buy_now, duration, at)
    if after is not market:
        commit(account, {'listing': receipt}, raw, {market_store.NAME: encode(after)})
    return receipt


def sale_price(listing):
    return listing['buy_now'] or listing['starting_bid']


def settle_sale(listing, football, credits, at, policy=None):
    """Apply a bot purchase of a player listing: (football, credits, receipt)."""
    policy = policy or economy.load_policy()
    instance = listing['item']['id']
    price = sale_price(listing)
    fee = economy.fee(price, policy)
    from .market_items import retire
    kind = listing['item'].get('kind', 'player')
    football = retire(football, kind, instance)
    receipt = {'trade_id': listing['trade_id'], 'buyer': 'bot', 'price': price, 'fee': fee,
               'net': price - fee, 'instance_id': instance, 'at': at,
               'credits_before': credits, 'credits_after': credits + price - fee}
    return football, credits + price - fee, receipt


def plan_clear_sold(market, trade_id):
    """(changed, updated market) clearing one SOLD row; exact retries change nothing."""
    listing = next((l for l in market['listings'] if l['trade_id'] == trade_id), None)
    if listing is None or listing['seller'] != 'player' or listing['state'] != 'closed':
        raise ValueError('Not a sold Transfer List item')
    if listing.get('sold_cleared'):
        return False, market
    after = copy.deepcopy(market)
    target = next(l for l in after['listings'] if l['trade_id'] == trade_id)
    target['sold_cleared'] = True
    return True, after


@account_locked
def clear_sold(account, trade_id):
    """1400 genuine CLEAR SOLD ITEMS: GET ut/delete/.../trade/<id> per sold row."""
    account = Path(account)
    recover(account)
    raw = {market_store.NAME: (account / market_store.NAME).read_bytes()}
    changed, after = plan_clear_sold(market_store.load(account), trade_id)
    if changed:
        commit(account, {'clear_sold': trade_id}, raw, {market_store.NAME: encode(after)})
