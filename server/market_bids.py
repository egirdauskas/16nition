"""Auction bids on bot listings (MARKET-005) and the lazy market event pass.

Genuine request (1397): POST trade/<id>/offer {"bid":<amount>,"itemData":[]},
the same route as Buy Now (parser 02307d94 reads only errorState/credits).

Revival policy (user design 3 Nov 2026, numbers in market-economy policy):
- A bid holds its coins immediately; the reply reports the reduced balance.
- Whether a bot answers, when, and with what amount is decided once, when the
  bid is placed, from the bot's seeded reservation price; nothing rerolls.
- Due events are applied lazily by `apply_due` before any read: a bot outbid
  refunds the player's hold; at expiry the highest bidder wins (a player win
  creates the owned card, Unassigned) and the listing closes.
Every change is one prepared multi-file intent (market_settlement.commit).
"""

import copy
import json
from pathlib import Path

from . import market_economy as economy
from . import market_store
from .account_transaction import account_locked
from .market_settlement import commit, encode, recover


def card_of(listing):
    from .market_items import listing_facts
    return listing_facts(listing)


def minimum_bid(listing, policy=None):
    if listing['current_bid'] == 0:
        return listing['starting_bid']
    return economy.next_bid(listing['current_bid'], policy)


def bot_response(listing, bid, at, policy=None):
    """The bot's answer to a player bid: {'at', 'amount'} or None (decided once)."""
    policy = policy or economy.load_policy()
    rule = policy['bidding']
    count = len(listing.get('player_bids', []))
    # One competing bot per auction with one fixed limit; only its timing varies per bid.
    reservation = economy.bot_reservation(f"bid:{listing['trade_id']}", card_of(listing), policy)
    amount = economy.next_bid(bid, policy)
    if reservation < amount or amount >= listing['buy_now']:
        return None
    low, high = rule['bot_response_delay_seconds']
    delay = economy.rng('bid-delay', listing['trade_id'], count).randint(low, high)
    when = min(at + delay, listing['expires_at'] - 1)
    if when <= at:
        return None
    return {'at': when, 'amount': amount}


def plan_bid(market, credits, trade_id, bid, at):
    """(receipt, updated market) for a valid player bid; ValueError otherwise. No writes."""
    listing = next((l for l in market['listings'] if l['trade_id'] == trade_id), None)
    if listing is None:
        raise ValueError('Unknown trade')
    previous = listing.get('player_bids') or []
    if previous and previous[-1]['bid'] == bid and listing.get('high_bidder') == 'player':
        return previous[-1], market          # exact retry of the standing bid
    if listing['seller'] != 'bot' or listing['state'] != 'active' or listing['expires_at'] <= at:
        raise ValueError('Trade not available')
    if listing.get('high_bidder') == 'player':
        raise ValueError('Already the highest bidder')
    if bid < minimum_bid(listing) or bid >= listing['buy_now'] or bid != economy.round_price(bid):
        raise ValueError('Invalid bid')
    if credits < bid:
        raise ValueError('Insufficient coins')
    receipt = {'trade_id': trade_id, 'bid': bid, 'at': at,
               'credits_before': credits, 'credits_after': credits - bid}
    after = copy.deepcopy(market)
    target = next(l for l in after['listings'] if l['trade_id'] == trade_id)
    answer = bot_response(target, bid, at)
    target.update(
        current_bid=bid, high_bidder='player', player_hold=bid, watched=True,
        player_bids=previous + [receipt], bot_response=answer,
    )
    return receipt, after


@account_locked
def place_bid(account, trade_id, bid, at):
    from .local_profile import validate_credits

    account = Path(account)
    apply_due(account, at)
    raw = {name: (account / name).read_bytes() for name in ('profile.json', market_store.NAME)}
    profile = json.loads(raw['profile.json'])
    credits = validate_credits(profile.get('credits', 0))
    market = market_store.load(account)
    receipt, after = plan_bid(market, credits, trade_id, bid, at)
    if after is market:
        return receipt
    commit(account, {'bid': receipt}, raw, {
        'profile.json': encode(dict(profile, credits=receipt['credits_after'])),
        market_store.NAME: encode(after),
    })
    return receipt


def reclaimed_listings(account, market):
    """Expired player listings whose card has left the Transfer List since (sent to club etc.)."""
    stale = [l for l in market['listings']
             if l['seller'] == 'player' and l['state'] == 'expired' and not l.get('reclaimed')]
    if not stale:
        return []
    from .local_content import ContentCatalog
    from .local_football import FootballStore, item_pile
    football = FootballStore(Path(account) / 'football.json', ContentCatalog(Path(account) / 'content.json')).load(1)
    from .local_football import owned_instance_ids
    owned = owned_instance_ids(football)
    return [l['trade_id'] for l in stale
            if l['item']['id'] not in owned or item_pile(football, l['item']['id']) != 'trade']


def due_events(market, at):
    """Listings with a bot outbid or an auction end due at `at` (oldest first)."""
    due = []
    for listing in market['listings']:
        if listing['seller'] == 'player' and listing['state'] == 'active':
            if market_store.due_bot_sale(listing, at):
                due.append((listing['bot_sale_at'], 'sold', listing['trade_id']))
            elif listing['expires_at'] <= at:
                due.append((listing['expires_at'], 'expired', listing['trade_id']))
            continue
        if listing['seller'] != 'bot' or listing['state'] != 'active' or not listing.get('player_bids'):
            continue
        answer = listing.get('bot_response')
        if listing.get('high_bidder') == 'player' and answer and answer['at'] <= at:
            due.append((answer['at'], 'outbid', listing['trade_id']))
        elif listing['expires_at'] <= at:
            due.append((listing['expires_at'], 'end', listing['trade_id']))
    return sorted(due)


@account_locked
def apply_due(account, at):
    """Apply every due outbid/auction end once, atomically; returns the events applied."""
    from .local_content import ContentCatalog
    from .local_football import FootballStore, ItemLocation, OwnedPlayerItem, owned_instance_ids, validate
    from dataclasses import replace

    account = Path(account)
    recover(account)
    if not (account / market_store.NAME).exists():
        return []
    market = market_store.load(account)
    events = due_events(market, at)
    reclaimed = reclaimed_listings(account, market)
    if not events and not reclaimed:
        return []
    names = ('profile.json', 'football.json', market_store.NAME)
    raw = {name: (account / name).read_bytes() for name in names}
    profile = json.loads(raw['profile.json'])
    store = FootballStore(account / 'football.json', ContentCatalog(account / 'content.json'))
    football = store.load(1)
    credits_before = profile['credits']
    football_before = football
    after = copy.deepcopy(market)
    by_id = {l['trade_id']: l for l in after['listings']}
    applied = []
    for trade_id in reclaimed:
        by_id[trade_id]['reclaimed'] = True
        applied.append({'kind': 'reclaimed', 'trade_id': trade_id, 'at': at})
    for when, kind, trade_id in events:
        listing = by_id[trade_id]
        if kind == 'sold':
            from .market_listings import settle_sale
            football, profile['credits'], receipt = settle_sale(listing, football, profile['credits'], when)
            listing.update(state='closed', settlement=receipt)
            applied.append({'kind': 'sold', 'trade_id': trade_id, 'at': when})
            continue
        if kind == 'expired':
            listing['state'] = 'expired'
            applied.append({'kind': 'expired', 'trade_id': trade_id, 'at': when})
            continue
        if kind == 'outbid':
            profile['credits'] = profile['credits'] + listing['player_hold']
            listing.update(current_bid=listing['bot_response']['amount'], high_bidder='bot', player_hold=0)
            applied.append({'kind': 'outbid', 'trade_id': trade_id, 'at': when})
            if listing['expires_at'] > at:
                continue
            when = listing['expires_at']
        receipt = {'trade_id': trade_id, 'buyer': listing['high_bidder'], 'price': listing['current_bid'], 'at': when}
        if listing['high_bidder'] == 'player':
            instance = football.next_instance_id or max(owned_instance_ids(football), default=0) + 1
            item = listing['item']
            if 'kind' in item:
                from .market_items import grant
                football = grant(football, item, instance)
            else:
                owned = OwnedPlayerItem(instance, item['resource_id'], 99, market_store.item_formation(listing),
                                        special_version_id=item.get('special_version_id'))
                football = replace(
                    football, owned_items=football.owned_items + (owned,), next_instance_id=instance + 1,
                    inventory_locations=football.inventory_locations + (ItemLocation(instance, 'unassigned'),),
                )
            receipt.update(instance_id=instance, resource_id=item['resource_id'],
                           special_version_id=item.get('special_version_id'))
            listing['player_hold'] = 0       # the held coins become the payment
        listing.update(state='closed', settlement=receipt)
        applied.append({'kind': 'won' if receipt['buyer'] == 'player' else 'lost', 'trade_id': trade_id, 'at': when})
    changes = {market_store.NAME: encode(after)}
    if profile['credits'] != credits_before:
        changes['profile.json'] = encode(profile)
    if football is not football_before:
        validate(football, store.catalog)
        changes['football.json'] = encode(FootballStore.encoded(football))
    commit(account, {'events': applied}, raw, changes)
    return applied
