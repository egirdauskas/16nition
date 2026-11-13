"""Versioned revival exchange choices, separate from native wire/ownership."""
import hashlib
import json
from pathlib import Path

PATH = Path(__file__).parent/'policy/player-exchange-revival-v2.json'
VERSION = 'player_exchange_revival_v2'
VERSIONS = ('player_exchange_revival_v1', VERSION)
TIERS = ('common_bronze','rare_bronze','common_silver','rare_silver','common_gold','rare_gold')


def load(path):
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    validate(value)
    return value, hashlib.sha256(raw).hexdigest()


def validate(value):
    if (value.get('version') not in VERSIONS or value.get('classification') != 'revival_policy' or
            value.get('default_enabled') is not False or value.get('tiers') != list(TIERS) or
            value.get('native_score') != 'sum_of_selected_owned_player_discard_values' or
            value.get('input_count') != [2,10] or value.get('free_replacement_draws') != 1 or
            value.get('coins_charged') != 0 or value.get('xp_awarded') != 0 or
            value.get('reward_tradeable') is not True):
        raise ValueError('Unsupported exchange policy/mechanics')
    def weights(v, size):
        if (type(v) is not list or len(v) != size or any(type(x) is not int or x < 0 for x in v) or sum(v) != 100):
            raise ValueError('Invalid exchange probability weights')
    weights(value.get('reward_count_weights'), 3)
    ranges = value.get('ranges')
    if type(ranges) is not list or not ranges:
        raise ValueError('Missing exchange range table')
    previous = -1
    for r in ranges:
        if type(r) is not dict or set(r) != {'upperLimit','lowerPackLevel','upperPackLevel','tier_weights'}:
            raise ValueError('Invalid exchange range fields')
        if (type(r['upperLimit']) is not int or not previous < r['upperLimit'] <= 0x7fffffff or
                any(type(r[k]) is not int for k in ('lowerPackLevel','upperPackLevel')) or
                not 0 <= r['lowerPackLevel'] <= r['upperPackLevel'] < len(TIERS)):
            raise ValueError('Invalid exchange range limits')
        weights(r['tier_weights'], 6)
        eligible = [i for i,w in enumerate(r['tier_weights']) if w]
        if eligible != list(range(r['lowerPackLevel'],r['upperPackLevel']+1)):
            raise ValueError('Displayed exchange range disagrees with reward pool')
        previous = r['upperLimit']
    if previous != 0x7fffffff:
        raise ValueError('Exchange range table must cover the complete native score')
    return value


def native_ranges(policy):
    return [{k:r[k] for k in ('upperLimit','lowerPackLevel','upperPackLevel')} for r in policy['ranges']]


def range_for(policy, score):
    if type(score) is not int or not 0 < score <= 0x7fffffff:
        raise ValueError('Positive bounded exchange score required')
    return next(r for r in policy['ranges'] if score <= r['upperLimit'])
