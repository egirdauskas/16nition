"""Big-five gold supply boost for bot Market listings (user, 5 November 2026).

The base supply draws a tier by weight, then a card uniformly within it. This
overlay splits each gold tier into its big-five-league part and the rest,
multiplies the big-five part's weight, and grows the standing bot inventory by
the same added weight. Expected counts of every other kind of listing stay the
same; big-five golds double. Only listings generated after selection change:
existing listings are persisted and never regenerated.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

PATH = Path(__file__).parent / 'policy/market-supply-big5-v1.json'
VERSION = 'market_supply_big5_v1'
MARKER = 'market-supply-big5.json'
_CACHE = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def policy():
    raw = PATH.read_bytes()
    key = hashlib.sha256(raw).digest()
    if key not in _CACHE:
        value = json.loads(raw)
        if (value.get('version') != VERSION or value.get('default_enabled') is not False
                or value.get('big_five_multiplier', 0) < 1):
            raise ValueError('Invalid big-five supply policy')
        _CACHE[key] = value
    return deepcopy(_CACHE[key])


def enabled(account):
    if account is None:
        return False
    marker = Path(account).resolve() / MARKER
    if not marker.is_file():
        return False
    value = json.loads(marker.read_bytes())
    if set(value) != {'version', 'account', 'policy_sha256'} or value['version'] != VERSION:
        raise ValueError('Invalid big-five supply selector')
    if value['account'] != str(Path(account).resolve()):
        return False          # copied from another account: inactive here
    if value['policy_sha256'] != sha(PATH):
        raise ValueError('Big-five supply policy changed after selection')
    return True


def marker_for(account):
    policy()
    return {'version': VERSION, 'account': str(Path(account).resolve()), 'policy_sha256': sha(PATH)}


_SPLIT = {}


def split_pools(pools):
    """Tier pools with each gold tier split into ':big5' and ':rest' parts (cached)."""
    key = (id(pools), tuple(sorted(pools)), sha(PATH))
    if key not in _SPLIT:
        _SPLIT.clear()
        _SPLIT[key] = _split(pools)
    return _SPLIT[key]


def _split(pools):
    from .card_pool import card_index
    from .market_economy import _league_by_team
    value = policy()
    leagues = set(value['big_five_league_ids'])
    by_team = _league_by_team()
    index = card_index()
    result = {}
    for name, rows in pools.items():
        if name not in value['gold_tiers']:
            result[name] = rows
            continue
        big = [r for r in rows if by_team.get(index[r[0]].team_id) in leagues]
        rest = [r for r in rows if by_team.get(index[r[0]].team_id) not in leagues]
        result[name + ':big5'] = big
        result[name + ':rest'] = rest
    return result


def weights(base_weights, pools):
    """Tier weights over split_pools(pools) and the added total weight."""
    value = policy()
    split = split_pools(pools)
    result = {}
    added = 0
    for name, weight in base_weights.items():
        if name not in value['gold_tiers']:
            result[name] = weight
            continue
        rows = pools[name]
        share = len(split[name + ':big5']) / len(rows)
        result[name + ':big5'] = weight * share * value['big_five_multiplier']
        result[name + ':rest'] = weight * (1 - share)
        added += weight * share * (value['big_five_multiplier'] - 1)
    return result, added


def inventory_size(base_size, base_weights, pools):
    """Grow the standing inventory so other listing kinds keep their counts."""
    _, added = weights(base_weights, pools)
    return round(base_size * (sum(base_weights.values()) + added) / sum(base_weights.values()))
