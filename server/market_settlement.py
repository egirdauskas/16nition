"""Atomic Buy Now settlement for bot listings (MARKET-002/004), unwired.

Player buys a bot listing: the listing closes in market.json, the price leaves
profile.json and a new owned player (same supplied card/special version) enters
football.json, as one prepared multi-file intent recovered before any read.
Wiring to a wire route waits for the genuine Buy Now request capture.
"""

import copy
import json
from pathlib import Path

from .account_transaction import account_locked, atomic, recover_images
from . import market_store

INTENT = 'market-intent.json'


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


@account_locked
def recover(account):
    path = Path(account) / INTENT
    if not path.exists():
        return
    intent = json.loads(path.read_bytes())
    if set(intent) != {'version', 'receipt', 'images'} or intent['version'] != 'market_settlement_v1':
        raise ValueError('Unknown market intent')
    recover_images(Path(account), intent['images'])
    path.unlink()


@account_locked
def buy_now(account, trade_id, price, at):
    """Return the settled receipt; exact retries return the same receipt."""
    from .local_content import ContentCatalog
    from .local_football import FootballStore, ItemLocation, OwnedPlayerItem
    from .local_profile import validate_credits

    account = Path(account)
    recover(account)
    market = market_store.load(account)
    listing = next((l for l in market['listings'] if l['trade_id'] == trade_id), None)
    if listing is None:
        raise ValueError('Unknown trade')
    receipt = listing.get('settlement')
    if receipt is not None:
        if receipt['buyer'] == 'player' and receipt['price'] == price:
            return receipt        # exact retry
        raise ValueError('Trade already closed')
    if listing['state'] != 'active' or listing['expires_at'] <= at or listing['seller'] != 'bot':
        raise ValueError('Trade not available')
    if price != listing['buy_now']:
        raise ValueError('Buy Now price differs from listing')
    raw = {name: (account / name).read_bytes() for name in ('profile.json', 'football.json', market_store.NAME)}
    profile = json.loads(raw['profile.json'])
    credits = validate_credits(profile.get('credits', 0))
    if credits < price:
        raise ValueError('Insufficient coins')
    store = FootballStore(account / 'football.json', ContentCatalog(account / 'content.json'))
    football = store.load(1)
    from .local_football import owned_instance_ids
    instance = football.next_instance_id or max(owned_instance_ids(football), default=0) + 1
    item = listing['item']
    from dataclasses import replace
    from .local_football import validate
    if 'kind' in item:
        from .market_items import grant
        updated = grant(football, item, instance)
    else:
        owned = OwnedPlayerItem(instance, item['resource_id'], 99, market_store.item_formation(listing),
                                special_version_id=item['special_version_id'])
        updated = replace(
            football, owned_items=football.owned_items + (owned,), next_instance_id=instance + 1,
            inventory_locations=football.inventory_locations + (ItemLocation(instance, 'unassigned'),),
        )
    validate(updated, store.catalog)
    receipt = {'trade_id': trade_id, 'buyer': 'player', 'price': price, 'instance_id': instance,
               'resource_id': item['resource_id'], 'special_version_id': item.get('special_version_id'),
               'credits_before': credits, 'credits_after': credits - price, 'at': at}
    after_profile = dict(profile, credits=credits - price)
    after_market = copy.deepcopy(market)
    target = next(l for l in after_market['listings'] if l['trade_id'] == trade_id)
    target.update(state='closed', settlement=receipt)
    commit(account, receipt, raw, {
        'profile.json': encode(after_profile),
        'football.json': encode(FootballStore.encoded(updated)),
        market_store.NAME: encode(after_market),
    })
    return receipt


def commit(account, receipt, raw, after):
    """Write one prepared multi-file intent (before/after images), then apply it.

    `raw` holds the bytes each file had when the change was planned; recovery
    refuses if any file has since changed to something else.
    """
    images = [
        {'name': name, 'before': raw[name].hex(), 'after': data.hex()}
        for name, data in sorted(after.items()) if data != raw.get(name)
    ]
    if not images:
        return
    atomic(Path(account) / INTENT, encode({'version': 'market_settlement_v1', 'receipt': receipt, 'images': images}))
    recover(account)
