"""Authorized revival XP/level arithmetic. No stock wire projection or access gates."""
import json
from math import isqrt
from pathlib import Path
from .local_profile import validate_credits

POLICY = Path(__file__).parent / 'policy/account-progression.json'

def nonnegative(value):
    if type(value) is not int or value < 0:
        raise ValueError('XP must be a nonnegative integer')
    return value

def level_state(total_xp):
    """Unbounded levels, exact integer inversion of cumulative requirements."""
    total_xp = nonnegative(total_xp)
    completed = (isqrt(275 * 275 + 100 * total_xp) - 275) // 50
    spent = 25 * completed * completed + 275 * completed
    return {'total_xp': total_xp, 'level': completed + 1,
            'level_xp': total_xp - spent, 'next_level_xp': 300 + 50 * completed}

def load_progression_policy(path=POLICY):
    value = json.loads(Path(path).read_text())
    expected = {'classification', 'version', 'default_enabled', 'stock_xp_enabled',
                'division10_xp', 'xp_division_step_percent', 'first_level_requirement',
                'level_requirement_step', 'coin_multiplier', 'coin_level_step_percent',
                'division_match_base_coins', 'rounding', 'pack_grants_enabled',
                'season_grants_enabled', 'rationale'}
    if set(value) != expected:
        raise ValueError('Unexpected progression policy fields')
    fixed = {'classification': 'revival_policy', 'version': 'account_progression_v1',
             'default_enabled': False, 'stock_xp_enabled': False,
             'division10_xp': {'W': 100, 'D': 60, 'L': 30},
             'xp_division_step_percent': 10, 'first_level_requirement': 300,
             'level_requirement_step': 50, 'coin_multiplier': 15,
             'coin_level_step_percent': 2, 'rounding': 'floor_integer_coins',
             'pack_grants_enabled': False, 'season_grants_enabled': False}
    # Strict types exclude bool-as-int and altered formulas.
    for key, expected_value in fixed.items():
        if type(value[key]) is not type(expected_value) or value[key] != expected_value:
            raise ValueError('Unsupported progression policy')
    rows = value['division_match_base_coins']
    if type(rows) is not dict or set(rows) != {str(i) for i in range(1, 11)}:
        raise ValueError('Ten explicit division match reward rows required')
    for row in rows.values():
        if type(row) is not dict or set(row) != {'W', 'D', 'L'}:
            raise ValueError('Explicit W/D/L coin amounts required')
        for amount in row.values():
            validate_credits(amount)
    return value

def quote(policy, division, result, start_total_xp):
    if type(division) is not int or not 1 <= division <= 10 or result not in ('W','D','L'):
        raise ValueError('Invalid division/result')
    start = level_state(start_total_xp)
    xp = policy['division10_xp'][result] * (20 - division) // 10
    base = policy['division_match_base_coins'][str(division)][result]
    # Amounts in configuration are BEFORE the authorized 15x multiplier.
    coins = validate_credits(base * 15 * (50 + start['level'] - 1) // 50)
    return {'policy_version': policy['version'], 'classification': 'revival_policy',
            'division': division, 'result': result, 'start': start,
            'xp': xp, 'after': level_state(start_total_xp + xp),
            'coins': coins, 'coin_multiplier_numerator': 50 + start['level'] - 1,
            'coin_multiplier_denominator': 50, 'base_coins_before_15x': base}
