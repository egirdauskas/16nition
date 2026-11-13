"""Direct delivery of individual-card Store purchases (explicit revival_policy).

Stock evidence (StoreCommonModel purchase callback): a successful purchase
navigates to Unassigned with the pack reveal and best-card popup. Purchase and
opening replies share one native factory/parser/item install, so a positive
purchase itemList uses the same proven install as an opening reply.

The backend composes two existing journals: the purchase receipt (debit plus a
private entitlement) and the opening receipt (ownership allocation). The
purchase receipt records ``delivery: direct`` so every retry is deterministic,
independent of later marker or policy changes.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = Path(__file__).parent / 'policy/store-direct-delivery-v1.json'
MARKER = 'store-direct-delivery.json'
VERSION = 'store_direct_delivery_v1'
DIRECT = 'direct'
_POLICY_CACHE = {}
_MARKER_CACHE = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validated_policy(raw):
    value = json.loads(raw)
    if (
        type(value) is not dict
        or value.get('version') != VERSION
        or value.get('classification') != 'revival_policy'
        or value.get('default_enabled') is not False
        or type(value.get('selections')) is not list
        or not value['selections']
        or any(type(s) is not str for s in value['selections'])
    ):
        raise ValueError('Invalid Store direct-delivery policy')
    return value


def policy(path=PATH):
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).digest()
    if digest not in _POLICY_CACHE:
        _POLICY_CACHE[digest] = _validated_policy(raw)
    return deepcopy(_POLICY_CACHE[digest])


def _validated_marker(raw):
    value = json.loads(raw)
    if (
        type(value) is not dict
        or set(value) != {'version', 'account', 'policy_sha256'}
        or value['version'] != VERSION
        or any(type(v) is not str or not v for v in value.values())
    ):
        raise ValueError('Invalid Store direct-delivery selector')
    return value


def enabled(account):
    """Marker-selected per account; absent marker keeps the wrapper policy."""
    account = Path(account).resolve()
    marker = account / MARKER
    if not marker.exists():
        return False
    if marker.is_symlink():
        raise ValueError('Direct-delivery selector must be a regular file')
    raw = marker.read_bytes()
    digest = hashlib.sha256(raw).digest()
    if digest not in _MARKER_CACHE:
        if len(_MARKER_CACHE) >= 8:
            _MARKER_CACHE.clear()
        _MARKER_CACHE[digest] = _validated_marker(raw)
    value = _MARKER_CACHE[digest]
    if value['account'] != str(account):
        raise ValueError('Direct-delivery selector belongs to another account')
    if value['policy_sha256'] != sha(PATH):
        raise ValueError('Direct-delivery policy changed after selection')
    return True


def marker_for(account):
    account = Path(account).resolve()
    policy()
    return {'version': VERSION, 'account': str(account), 'policy_sha256': sha(PATH)}


def applies(account, definition):
    if not enabled(account):
        return False
    from .local_packs import DEFINITIONS
    rule = DEFINITIONS.get(definition)
    if rule is None:
        raise ValueError('Unknown direct-delivery definition')
    return rule.get('selection') in policy()['selections']


def is_direct(receipt):
    return receipt.get('delivery') == DIRECT


def opening_identity(store, receipt):
    from . import native_pack_sessions as sessions
    if sessions.selected(store.path.parent):
        return {'sid': receipt['session_id'], 'wire_id': receipt['product_id']}
    return None


def preview(store, football, receipt):
    """Pure opening preview for a (possibly uncommitted) direct purchase."""
    if not is_direct(receipt):
        raise ValueError('Not a direct-delivery purchase')
    key = receipt['entitlement']['catalog_id']
    value = store.load()
    done = next((r for r in value['consumed'] if r['catalog_id'] == key), None)
    if done is not None:
        return done
    return store.preview_entitlement(
        receipt['entitlement'], football, opening_identity(store, receipt), value=value,
    )


def commit(store, football, receipt):
    """Open the purchased private entitlement; idempotent on retry."""
    if not is_direct(receipt):
        raise ValueError('Not a direct-delivery purchase')
    key = receipt['entitlement']['catalog_id']
    return store.open(key, football, opening_identity(store, receipt))


def completed(store, receipt):
    key = receipt['entitlement']['catalog_id']
    opened = next((r for r in store.load()['consumed'] if r['catalog_id'] == key), None)
    if opened is None:
        raise ValueError('Direct-delivery purchase has no completed opening')
    return opened
