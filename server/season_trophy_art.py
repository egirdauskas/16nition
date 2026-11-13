"""Original supplied selector artwork; local competition-to-shape assignment.

Only read-only competition metadata uses this policy. It does not create owned
trophies, alter competition identity, or modify client assets and reward rules.
"""
import json
from pathlib import Path

POLICY = Path(__file__).parent/'policy/season-trophy-art-v1.json'


def metadata_art(competition):
    value = json.loads(POLICY.read_bytes())
    if (value.get('version') != 'season_trophy_art_v1'
            or value.get('classification') != 'revival_policy_original_art_assignment'
            or value.get('source') != 'data\\ux\\assetsLicensedTrophies.big'):
        raise ValueError('Unsupported original trophy presentation policy')
    family = competition.key.split('_', 1)[1]
    shape = value['families'].get(family)
    if type(shape) is not int or not 1100 <= shape <= 1170:
        raise ValueError('No admitted original trophy shape for competition')
    #02190204 ->01012aec ->01010698 uses assetName without the owned-card
    #"item" suffix. The patch Lua supplies badgeId to the $Trophies provider.
    return {'assetName': f'trophy_{shape}_gold', 'silName': f'trophy_{shape}_dark'}
