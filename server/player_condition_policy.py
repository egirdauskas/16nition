"""Authorized offline condition policy, separate from preserved native reports.

Original match reports may contain the stock engine's temporary condition loss.
Those reports remain evidence; they never determine persisted player condition.
All supported player item responses restore the client's canonical values.
"""
import json
from functools import lru_cache
from pathlib import Path

POLICY = Path(__file__).parent / 'policy' / 'player-condition.json'

@lru_cache(maxsize=1)
def player_condition():
    value = json.loads(POLICY.read_text())
    if value != {
        'version': 'offline_player_condition_v1',
        'classification': 'revival_policy',
        'fitness': 99,
        'morale': 99,
        'persist_native_condition_loss': False,
    }:
        raise ValueError('Unsupported offline player condition policy')
    return {'fitness': value['fitness'], 'morale': value['morale']}
