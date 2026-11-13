"""STORE-006 release-demo Store offers (explicit revival_policy, user 6 Nov 2026).

An append-only layer on top of the certified Store: the account catalog
(products.json) and every pinned release marker stay byte-identical. Offers
come from a versioned policy and an account selector, and demonstrate three
offer properties:
- ``available_until`` (epoch seconds): hidden and unpurchasable afterwards;
- ``once``: an offer that disappears for good after one purchase (counted
  across all pack sessions, unlike per-session purchase limits);
- a nationality-filtered pack definition (pack_policy ``nationality``).
Their native wire ids are a small block per definition (``wire_block``: first id,
slots) after the single-card caption bank (26792..), below private catalog ids
(30001). Every reserved id costs three descriptor texts in the client's
StorePackDescriptions sheet; 128-slot blocks made all Store texts disappear
(1507/1508), so blocks are kept small.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

POLICY_PATH = Path(__file__).parent / 'policy/store-demo-offers-v1.json'
VERSION = 'store_demo_offers_v1'
MARKER = 'store-demo-offers.json'
NAMESPACE_END = 30001
BANK_END = 26792  # end of the single-card caption bank
_CACHE = {}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _validated(raw):
    value = json.loads(raw)
    keys = {'version', 'classification', 'approved', 'default_enabled', 'offers', 'retired_products'}
    if (type(value) is not dict or set(value) != keys or value['version'] != VERSION
            or value['classification'] != 'revival_policy' or value['default_enabled'] is not False):
        raise ValueError('Invalid demo offer policy')
    from .local_packs import DEFINITIONS
    from .local_profile import validate_credits
    seen = set()
    for offer in value['offers']:
        allowed = {'product_id', 'definition', 'coin_price', 'repeatable', 'featured', 'available_until',
                   'once', 'captions', 'wire_block', 'available_from', 'time_banner'}
        required = {'product_id', 'definition', 'coin_price', 'captions', 'wire_block'}
        if (set(offer) - allowed or not required <= set(offer)
                or type(offer['product_id']) is not int or not 56000 <= offer['product_id'] <= 56999
                or offer['definition'] not in DEFINITIONS or offer['definition'] in seen
                or set(offer['captions']) != {'NAME', 'DESC', 'SHORT'}
                or offer['captions']['NAME'] != DEFINITIONS[offer['definition']]['name']):
            raise ValueError('Invalid demo offer')
        validate_credits(offer['coin_price'])
        if offer['coin_price'] < 1:
            raise ValueError('The stock Store cannot sell an offer for 0 coins (run 1502)')
        # Under native pack sessions every Store offer is a repeatable SKU (receipts
        # carry sku_id/next_product_id, run 1504); ``once`` hides it after one purchase.
        if offer.get('repeatable') is not True or ('once' in offer and offer['once'] is not True):
            raise ValueError('Demo offers are repeatable session SKUs; once must be true when set')
        if 'available_until' in offer and type(offer['available_until']) is not int:
            raise ValueError('Invalid offer window')
        if 'time_banner' in offer and (
                offer['time_banner'] is not True or type(offer.get('available_from')) is not int
                or 'available_until' not in offer or offer['available_from'] >= offer['available_until']):
            raise ValueError('A time banner needs available_from < available_until')
        if 'available_from' in offer and 'time_banner' not in offer:
            raise ValueError('available_from is only used by the time banner')
        seen.add(offer['definition'])
    if type(value['retired_products']) is not list or any(type(i) is not int for i in value['retired_products']):
        raise ValueError('Invalid retired Store products')
    previous_end = BANK_END
    for offer in value['offers']:
        block = offer['wire_block']
        if (type(block) is not list or len(block) != 2 or any(type(x) is not int for x in block)
                or block[0] < previous_end or not 2 <= block[1] <= 32
                or block[0] + block[1] > NAMESPACE_END):
            raise ValueError('Demo offer wire blocks must be small, ascending and after the bank')
        previous_end = block[0] + block[1]
    return value


def policy():
    raw = POLICY_PATH.read_bytes()
    digest = sha(raw)
    if digest not in _CACHE:
        _CACHE[digest] = _validated(raw)
    return deepcopy(_CACHE[digest])


def marker_for(account):
    policy()
    return {'version': VERSION, 'account': str(Path(account).resolve()),
            'policy_sha256': sha(POLICY_PATH.read_bytes())}


def selected(account):
    """Per-account selector; a copy bound to another account stays inactive."""
    account = Path(account).resolve()
    marker = account / MARKER
    if not marker.exists():
        return False
    if marker.is_symlink():
        raise ValueError('Demo offer selector must be a regular file')
    value = json.loads(marker.read_bytes())
    if (type(value) is not dict or set(value) != {'version', 'account', 'policy_sha256'}
            or value['version'] != VERSION):
        raise ValueError('Invalid demo offer selector')
    if value['account'] != str(account):
        return False
    if value['policy_sha256'] != sha(POLICY_PATH.read_bytes()):
        raise ValueError('Demo offer policy changed after selection')
    return True


def _receipts(account):
    """Completed purchases only: a prepared receipt is the purchase being validated (1505)."""
    path = Path(account) / 'purchases.json'
    if not path.exists():
        return []
    return json.loads(path.read_bytes())['receipts']


def extra_products(products_path, now=None):
    """Store rows to append for this account (open window, one-time offer not yet taken)."""
    account = Path(products_path).resolve().parent
    if not selected(account):
        return []
    now = time.time() if now is None else now
    taken = {r.get('sku_id', r['product_id']) for r in _receipts(account)}
    taken |= {r['entitlement']['definition'] for r in _receipts(account) if r.get('entitlement')}
    rows = []
    for offer in policy()['offers']:
        if 'available_until' in offer and now >= offer['available_until']:
            continue
        if offer.get('once') and (offer['product_id'] in taken or offer['definition'] in taken):
            continue
        row = {'product_id': offer['product_id'], 'definition': offer['definition'],
               'provenance': 'revival_policy', 'coin_price': offer['coin_price']}
        for key in ('repeatable', 'featured'):
            if key in offer:
                row[key] = offer[key]
        rows.append(row)
    return rows


def layout(account):
    """Appended caption blocks {definition: (first wire id, slots)} for a selected account."""
    if account is None or not selected(account):
        return {}
    return {o['definition']: tuple(o['wire_block']) for o in policy()['offers']}


def captions(definition):
    """User-defined (not recovered EA) texts for the demo pack definitions."""
    for offer in policy()['offers']:
        if offer['definition'] == definition:
            return dict(offer['captions'])
    return None


def layout_blocks():
    """All policy wire blocks (for size checks), independent of selection."""
    return [tuple(o['wire_block']) for o in policy()['offers']]


def retired_products(products_path):
    """Catalog product ids withdrawn from sale for a selected account (user, 6 Nov 2026)."""
    account = Path(products_path).resolve().parent
    if not selected(account):
        return set()
    return set(policy()['retired_products'])


def row_fields(product_id, products_path, now=None):
    """Extra Store-row fields for a demo offer of a selected account.

    ``time_banner`` (1518-1521): stock ``saleType`` TIME with ``start``/``end`` gives the orange
    LIMITED TIME banner and countdown. The row goes first (``_first``) because DraggableCarousel
    recycles PackComponents and the stock limited branch never re-shows a hidden banner.
    The isolated probe file ``store-demo-row-probe.json`` may add or override fields.
    """
    account = Path(products_path).resolve().parent
    if not selected(account):
        return {}
    offer = next((o for o in policy()['offers'] if o['product_id'] == product_id), None)
    if offer is None:
        return {}
    fields = {}
    if offer.get('time_banner'):
        fields = {'saleType': 'TIME', 'start': offer['available_from'],
                  'end': offer['available_until'], '_first': True}
    probe = _probe(account)
    if probe is not None and 'available_until' in offer:
        now = int(time.time() if now is None else now)
        until = offer['available_until']
        values = {'{until}': until, '{remaining}': max(0, until - now), '{until_ms}': until * 1000,
                  '{start}': until - 8 * 86400}
        for key, value in probe.get('fields', {}).items():
            fields[key] = values.get(value, value) if isinstance(value, str) else value
    return fields


def _probe(account):
    """Isolated-lab probe only (never the real account)."""
    root = Path(__file__).resolve().parents[1]
    probe = account / 'store-demo-row-probe.json'
    if root / 'reports' not in account.parents or account.name != 'isolated-account' or not probe.is_file():
        return None
    return json.loads(probe.read_bytes())


def envelope_fields(products_path, now=None):
    """Top-level Store-reply fields for a selected account.

    0230f82c parses the Store reply: key ``timestamp`` (0x1f1) -> result +0x3c,
    ``purchase`` (0x183) -> rows. 021ea8a4 copies +0x3c to the Store clock (+0x164)
    that 021e8768 subtracts from a TIME pack's ``end`` for ``timeRemaining``.
    Without it the clock is 0 and the countdown shows the whole epoch (1520).
    """
    account = Path(products_path).resolve().parent
    if not selected(account):
        return {}
    now = int(time.time() if now is None else now)
    fields = {'timestamp': now}
    probe = _probe(account)
    if probe is not None:
        for key, value in probe.get('envelope', {}).items():
            fields[key] = now if value == '{now}' else value
    return fields
