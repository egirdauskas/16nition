"""User-authorized prospective early season finish; no EA timing claim.

The final band must be the same with zero or maximum additional points. This
preserves a possible title after promotion and never invents unplayed matches.
Financial amounts, XP and source identities belong to the existing coordinator.
"""
import hashlib,json
from pathlib import Path
from .season_revival_policy import load_policy,POLICY as SEASON_POLICY

PATH=Path(__file__).parent/'policy/early-season-completion-v1.json'


def policy():
    value=json.loads(PATH.read_bytes())
    expected={'version':'early_season_completion_v1','classification':'revival_policy',
              'default_enabled':False,'stock_delivery_enabled':False,'trigger':'best_outcome_secured',
              'maximum_fixtures':10,'higher_outcome_opportunity':'preserve','unplayed_fixtures':'remain_unplayed'}
    if value!=expected or any(type(value[k]) is not type(v) for k,v in expected.items()):
        raise ValueError('Unsupported early season completion policy')
    return value


def snapshot(division):
    value=policy();row=load_policy().for_division(division)
    return {'version':value['version'],'classification':'revival_policy','division':division,
            'policy_sha256':hashlib.sha256(PATH.read_bytes()).hexdigest(),
            'season_policy_sha256':hashlib.sha256(SEASON_POLICY.read_bytes()).hexdigest(),
            'thresholds':{'maintenance':row.maintenance,'promotion':row.promotion,'championship':row.championship}}


def validate_snapshot(start):
    if type(start) is not dict or start!=snapshot(start.get('division')):
        raise ValueError('Invalid pinned season completion timing')
    return start


def evaluate(start,played,points):
    validate_snapshot(start);row=load_policy().for_division(start['division'])
    actual=row.evaluate(played,points)
    best=row.evaluate(10,actual['maximum_final_points'])
    if played==10 or (played>0 and actual['preview_band']==best['preview_band']):
        final=row.evaluate(10,points)
        # Only qualification changes. Retain actual played/remaining numbers;
        # the three unplayed fixtures after a seven-game title never become
        # fictitious losses, fixtures or additional match reward sources.
        final.update(matches_played=played,games_remaining=10-played,
                     maximum_final_points=actual['maximum_final_points'])
        return final
    return actual


def source_outcome(source,division,points,*,season_policy=None):
    start=source.get('season_completion_timing')
    if start is None:
        return (season_policy or load_policy()).for_division(division).evaluate(source['fixture'],points)
    if type(start) is not dict or not source.get('atomic_match') or start.get('division')!=division:
        raise ValueError('Early completion requires its accepted atomic source/division')
    return evaluate(start,source['fixture'],points)


def validate_source(source):
    start=source.get('season_completion_timing')
    if start is None:return
    validate_snapshot(start)
    if (not source.get('atomic_match') or not source.get('season_coin_start') or
            start['division']!=source.get('native_xp_start',{}).get('division')):
        raise ValueError('Early completion requires accepted atomic season rewards')
