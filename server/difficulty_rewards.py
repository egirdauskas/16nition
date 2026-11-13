"""Disabled prospective revival reward calculations, independent of wire DTOs.

Existing receipts retain their original division policy. This module does not
grant rewards, migrate sources or change native activation. A future adapter must
pin this snapshot at creation and use the existing atomic recovery journal.
"""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from .account_progression import level_state
from .local_profile import validate_credits
from .season_choice_reference import snapshot as competition_reference
from .season_choices import ChoiceDefinition, definition, load_catalog

POLICY = Path(__file__).parent / 'policy/difficulty-rewards-v1.json'
VERSION = 'difficulty_rewards_v1'
LABELS = ('Beginner', 'Amateur', 'Semi-Pro', 'Professional', 'World Class', 'Legendary', 'Ultimate')
BANDS = ('RELEGATION', 'MAINTENANCE', 'PROMOTION', 'CHAMPIONSHIP')


def _integer(value, lower, upper):
    return type(value) is int and lower <= value <= upper


def load_policy(path=POLICY):
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    fixed = {'classification': 'revival_policy', 'version': VERSION,
             'default_enabled': False, 'stock_delivery_enabled': False,
             'coin_tables_are_already_15x': True, 'coin_level_step_percent': 2,
             'xp_base': {'W': 100, 'D': 60, 'L': 30},
             'season_aggregate': 'arithmetic_mean_all_scheduled_fixtures',
             'rounding': 'floor_final_integer'}
    if (type(value) is not dict or set(value) != set(fixed) | {'calibration', 'tiers', 'rationale'}
            or any(type(value[k]) is not type(v) or value[k] != v for k, v in fixed.items())
            or not isinstance(value['rationale'], str) or not value['rationale']):
        raise ValueError('Unsupported difficulty reward policy or activation')
    calibration = value['calibration']
    expected = {'version': 'catalog_frequency_mean_of_approved_division_tables_v1',
                'catalog_sha256': sha256((POLICY.parent/'offline-season-choices-v1.json').read_bytes()).hexdigest(),
                'baseline_sha256': sha256((POLICY.parent/'offline-rewards-v1.json').read_bytes()).hexdigest(),
                'match_coin_rounding': 25, 'season_coin_rounding': 250, 'xp_percent_rounding': 1}
    if calibration != expected:
        raise ValueError('Difficulty calibration provenance differs')
    rows = value['tiers']
    if type(rows) is not dict or set(rows) != {str(i) for i in range(7)}:
        raise ValueError('Seven original difficulty tiers required')
    for i, name in enumerate(LABELS):
        row = rows[str(i)]
        if (type(row) is not dict or set(row) != {'label', 'match_coins', 'xp_scale_percent', 'season_coins'}
                or row['label'] != name or not _integer(row['xp_scale_percent'], 1, 10000)
                or type(row['match_coins']) is not dict or set(row['match_coins']) != set('WDL')
                or type(row['season_coins']) is not dict or set(row['season_coins']) != set(BANDS)):
            raise ValueError('Invalid difficulty reward tier')
        for amount in row['match_coins'].values():
            validate_credits(amount)
            if not amount: raise ValueError('Positive match amounts required')
        if not row['match_coins']['W'] > row['match_coins']['D'] > row['match_coins']['L']:
            raise ValueError('Match results must retain ordered rewards')
        previous = -1
        for band in BANDS:
            amount = row['season_coins'][band]
            if amount is None:
                if (i, band) != (0, 'RELEGATION'):
                    raise ValueError('Unresolved season tier')
                continue
            validate_credits(amount)
            if amount <= previous: raise ValueError('Season bands must retain ordered rewards')
            previous = amount
        if i:
            prior = rows[str(i-1)]
            if (row['xp_scale_percent'] < prior['xp_scale_percent']
                    or any(row['match_coins'][r] < prior['match_coins'][r] for r in 'WDL')
                    or any(prior['season_coins'][b] is not None and row['season_coins'][b] < prior['season_coins'][b] for b in BANDS)):
                raise ValueError('Difficulty rewards must be monotonic')
    return value


def snapshot(selected, fixture_index, start_total_xp):
    """Compact new-source quote inputs; the full scheduled season sets its value.

    All scheduled fixtures count even if an outcome becomes secured early. The
    immutable competition reference reconstructs their order without copying it.
    """
    if not isinstance(selected, ChoiceDefinition):
        raise ValueError('Explicit selected competition required; no legacy inference')
    selected.validate()
    if not _integer(fixture_index, 1, len(selected.fixtures)):
        raise ValueError('Invalid prospective fixture index')
    policy = load_policy()
    start = level_state(start_total_xp)
    histogram = Counter(f.difficulty for f in selected.fixtures)
    return {'version': VERSION, 'policy_sha256': sha256(POLICY.read_bytes()).hexdigest(),
            'competition_reference': competition_reference(selected),
            'fixture_index': fixture_index, 'difficulty': selected.fixtures[fixture_index-1].difficulty,
            'start_total_xp': start_total_xp, 'start_level': start['level'],
            'scheduled_difficulty_counts': [histogram[i] for i in range(len(policy['tiers']))]}


def validate_snapshot(value):
    keys = {'version', 'policy_sha256', 'competition_reference', 'fixture_index', 'difficulty',
            'start_total_xp', 'start_level', 'scheduled_difficulty_counts'}
    if type(value) is not dict or set(value) != keys or value['version'] != VERSION:
        raise ValueError('Invalid difficulty reward snapshot')
    ref = value['competition_reference']
    if (type(ref) is not dict or type(ref.get('competition_key')) is not str
            or ref['competition_key'] not in load_catalog()):
        raise ValueError('Unknown reward competition reference')
    selected = definition(load_catalog()[ref['competition_key']], ref.get('season_id'), ref.get('fixture_seed'))
    expected = snapshot(selected, value['fixture_index'], value['start_total_xp'])
    # Canonical JSON comparison also rejects bool-as-int replacements.
    if json.dumps(expected, sort_keys=True) != json.dumps(value, sort_keys=True):
        raise ValueError('Difficulty reward snapshot differs from selected fixture/policy')
    return selected


def match_quote(start, result):
    validate_snapshot(start)
    return match_values(start['difficulty'], start['start_total_xp'], result)


def match_values(difficulty, start_total_xp, result):
    """Shared Seasons/tournament arithmetic, without fabricating a season."""
    if type(result) is not str or result not in ('W', 'D', 'L'):
        raise ValueError('Explicit W/D/L result required')
    policy = load_policy()
    if type(difficulty) is not int or str(difficulty) not in policy['tiers']:
        raise ValueError('Explicit supported difficulty required')
    tier = policy['tiers'][str(difficulty)]
    before = level_state(start_total_xp)
    xp = policy['xp_base'][result] * tier['xp_scale_percent'] // 100
    multiplier = 50 + before['level'] - 1
    # Already15x table. Only the pre-fixture account level multiplies coins.
    coins = validate_credits(tier['match_coins'][result] * multiplier // 50)
    return {'policy_version': VERSION, 'classification': 'revival_policy',
            'policy_sha256': sha256(POLICY.read_bytes()).hexdigest(), 'difficulty': difficulty, 'result': result,
            'start': before, 'after': level_state(before['total_xp'] + xp),
            'xp': xp, 'xp_scale_percent': tier['xp_scale_percent'],
            'level1_coins_already_15x': tier['match_coins'][result],
            'coin_multiplier_numerator': multiplier, 'coin_multiplier_denominator': 50,
            'coins': coins}


def season_quote(start, band):
    selected = validate_snapshot(start)
    if type(band) is not str or band not in BANDS:
        raise ValueError('Unknown season outcome')
    if (selected.division_index == 10 and band == 'RELEGATION'
            or selected.division_index == 1 and band == 'PROMOTION'):
        raise ValueError('Inapplicable division boundary outcome')
    policy = load_policy()
    counts = start['scheduled_difficulty_counts']
    numerator = 0
    for difficulty, count in enumerate(counts):
        amount = policy['tiers'][str(difficulty)]['season_coins'][band]
        if count and amount is None:
            raise ValueError('Unresolved difficulty/outcome reward; no silent substitution')
        numerator += count * (amount or 0)
    return {'policy_version': VERSION, 'classification': 'revival_policy',
            'policy_sha256': start['policy_sha256'], 'band': band,
            'scheduled_difficulty_counts': list(counts), 'scheduled_matches': sum(counts),
            'aggregate_numerator': numerator, 'aggregate_denominator': sum(counts),
            'coins': validate_credits(numerator // sum(counts))}


def validate_source(source):
    """Join a prospective calculation to the accepted atomic source identity."""
    start = source.get('difficulty_reward_start')
    coin = source.get('coin_reward_start') or {}
    if start is None:
        if coin.get('policy_version') == VERSION:
            raise ValueError('Difficulty coin source lost its prospective snapshot')
        return
    selected = validate_snapshot(start)
    xp = source.get('native_xp_start') or {}
    if (source.get('atomic_match', {}).get('competition_reference') != start['competition_reference']
            or source.get('fixture') != start['fixture_index']
            or coin.get('policy_version') != VERSION
            or any(p.get('total_xp') != start['start_total_xp'] or p.get('level') != start['start_level']
                   or p.get('division') != selected.division_index for p in (coin, xp))):
        raise ValueError('Difficulty snapshot differs from accepted atomic source')
    season = source.get('season_coin_start')
    if season and season.get('competition_reference') != start['competition_reference']:
        raise ValueError('Match and season difficulty references differ')


def source_coin_quote(source, result):
    """Version dispatch uses the accepted source, never the running selector."""
    validate_source(source)
    start = source.get('difficulty_reward_start')
    if start is None:
        from .revival_rewards import match_coin_quote
        coin = source['coin_reward_start']
        return match_coin_quote(coin['division'], result, coin['total_xp'])
    calculation = match_quote(start, result)
    return {**calculation, 'amount': calculation['coins']}


def source_xp_quote(source, result):
    validate_source(source)
    start = source.get('difficulty_reward_start')
    if start is not None:
        return match_quote(start, result)
    from .account_progression import quote, load_progression_policy
    xp = source['native_xp_start']
    return quote(load_progression_policy(), xp['division'], result, xp['total_xp'])
