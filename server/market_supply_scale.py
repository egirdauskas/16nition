"""Overall bot Market stock scale (user, 5 November 2026: over 1,000 live listings).

Multiplies every category's standing bot stock (players, after any big-five
adjustment, and each item category) so the mix stays the same. Selected per
account; only how many listings are kept live changes, never existing ones.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

PATH = Path(__file__).parent / 'policy/market-supply-scale-v1.json'
VERSION = 'market_supply_scale_v1'
MARKER = 'market-supply-scale.json'
_CACHE = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def policy():
    raw = PATH.read_bytes()
    key = hashlib.sha256(raw).digest()
    if key not in _CACHE:
        value = json.loads(raw)
        if (value.get('version') != VERSION or value.get('default_enabled') is not False
                or type(value.get('multiplier')) is not int or not 1 <= value['multiplier'] <= 20):
            raise ValueError('Invalid Market scale policy')
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
        raise ValueError('Invalid Market scale selector')
    if value['account'] != str(Path(account).resolve()):
        return False          # copied from another account: inactive here
    if value['policy_sha256'] != sha(PATH):
        raise ValueError('Market scale policy changed after selection')
    return True


def marker_for(account):
    policy()
    return {'version': VERSION, 'account': str(Path(account).resolve()), 'policy_sha256': sha(PATH)}


def scaled(sizes, account):
    """Category stock sizes multiplied when the account selected the scale."""
    if not enabled(account):
        return sizes
    factor = policy()['multiplier']
    return {category: size * factor for category, size in sizes.items()}
