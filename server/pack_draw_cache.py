"""Bounded memo of pure pack selection, never account/ownership validation.

Every call fingerprints the complete current rule and eligible typed pool.
Changed inputs recompute; exceptions are not retained. Values contain only
frozen content references, with no owned IDs, wallet state or journal images.
"""
from collections import OrderedDict
import hashlib
import json
from threading import RLock

LIMIT = 256
_VALUES = OrderedDict()
_LOCK = RLock()


def selected(algorithm, identity, rule, pool, compute):
    rows = [(type(p).__name__, p.resource_id, p.special_version_id,
             p.base_rare, p.base_quality, getattr(p, 'item_family', 'player')) for p in pool]
    raw = json.dumps([identity, rule, rows], sort_keys=True, separators=(',', ':'),
                     allow_nan=False).encode()
    key = (algorithm, hashlib.sha256(raw).digest())
    with _LOCK:
        if key in _VALUES:
            _VALUES.move_to_end(key)
            return _VALUES[key]
    result = tuple(compute())
    with _LOCK:
        _VALUES[key] = result
        _VALUES.move_to_end(key)
        while len(_VALUES) > LIMIT:
            _VALUES.popitem(last=False)
    return result


def clear():
    with _LOCK:
        _VALUES.clear()
