"""Original text plus exact supplied card facts for prospective Store offers.

This is a local product presentation, not a recovered historical EA SKU list.
No marketing copy, football resources or account metadata are fabricated.
"""
import hashlib
import json
from pathlib import Path

PATH = Path(__file__).parent / 'policy/recovered-single-consumable-captions-v1.json'
_CACHE = {}
PLAYER_KEYS = (
    'PACE', 'SHOOTING', 'PASSING', 'DRIBBLING', 'DEFENDING', 'PHYSICAL',
)
KEEPER_KEYS = ('DIVING', 'HANDLING', 'KICKING', 'REFLEXES', 'ACCELERATION', 'POSITIONING')
REQUIRED_KEYS = {'FUT_UC_' + key for key in PLAYER_KEYS + KEEPER_KEYS} | {
    'Attribute_All', 'FUT_TRAINING_CARD_ONLY_ONE_MATCH',
    'FUT_CONSUMABLE_PLAYERTRAINING', 'FUT_CONSUMABLE_KEEPERTRAINING',
    'FUT_CONSUMABLE_PLAYERHEALING', 'FUT_CONSUMABLE_POSITIONMOD',
    'FUT_CONSUMABLE_FORMATIONMOD', 'FCC_CU_Arena_help_4',
    'LTXT_CONSUMABLES_PLAYER_POSITION', 'LTXT_CONSUMABLES_PLAYER_FORMATION',
    'LTXT_CONSUMABLES_MANAGER_FORMATION',
} | {'Injury_' + kind + '_desc' for kind in ('head', 'shoulder', 'arm', 'hip', 'leg', 'foot', 'All')}


def _text():
    raw = PATH.read_bytes()
    digest = hashlib.sha256(raw).digest()
    if digest not in _CACHE:
        value = json.loads(raw)
        if (
            value.get('version') != 'recovered_single_consumable_captions_v1'
            or value.get('classification') != 'recovered_supplied_stock_text'
            or value.get('source', {}).get('sha256') !=
                'a7d47d85769e922e2df6620e4c388a25a7fcae3cb4703f36d36b19de3d3511b2'
            or type(value.get('entries')) is not dict
            or set(value['entries']) != REQUIRED_KEYS
            or any(type(r) is not dict or type(r.get('value')) is not str
                   or not r['value'] for r in value['entries'].values())
        ):
            raise ValueError('Invalid original single-consumable caption provenance')
        if len(_CACHE) >= 8:
            _CACHE.clear()
        _CACHE[digest] = {k: r['value'] for k, r in value['entries'].items()}
    return _CACHE[digest]


def captions(definition):
    prefix = 'revival_single_consumable_'
    if not isinstance(definition, str) or not definition.startswith(prefix):
        return None
    from .store_single_consumables import category_ids, category_for
    from .local_consumables import inventory_reference
    from .consumable_effects import PLAYER_FORMATIONS, MANAGER_FORMATIONS, POSITION_PAIRS
    from .local_content_source import POSITION_WIRE
    from .local_formations import FORMATIONS
    category_ids(definition)  # Validate canonical admitted resource identity.
    resource_id = int(definition[len(prefix):-len('_v1')])
    row = inventory_reference(resource_id)
    subtype = row['cardsubtype']
    category = category_for(subtype)
    text = _text()
    if category in ('player_training', 'goalkeeper_training'):
        keeper = category == 'goalkeeper_training'
        index = subtype - (51 if keeper else 61)
        keys = KEEPER_KEYS if keeper else PLAYER_KEYS
        label = text['Attribute_All'] if index == 6 else text['FUT_UC_' + keys[index]]
        name = ('GK ' if keeper else '') + label + ' +' + str(row['amount'])
        desc = text['FUT_CONSUMABLE_KEEPERTRAINING' if keeper else 'FUT_CONSUMABLE_PLAYERTRAINING']
        desc += ' ' + text['FUT_TRAINING_CARD_ONLY_ONE_MATCH']
    elif category == 'healing':
        from .injury_effects import TYPES
        kind = 'All' if subtype == 218 else TYPES[subtype - 211]
        name = text['Injury_' + kind + '_desc'].replace('%1d', str(row['amount']))
        desc = text['FUT_CONSUMABLE_PLAYERHEALING']
    elif category == 'player_position':
        source, target = (POSITION_WIRE[p] for p in POSITION_PAIRS[subtype])
        name = text['LTXT_CONSUMABLES_PLAYER_POSITION'].replace('\n', ' ')
        name += f' {source} > {target}'
        desc = text['FUT_CONSUMABLE_POSITIONMOD']
    else:
        manager = category == 'manager_formation'
        mapping = MANAGER_FORMATIONS if manager else PLAYER_FORMATIONS
        formation = '-'.join(FORMATIONS[mapping[subtype]][1:])
        key = 'LTXT_CONSUMABLES_MANAGER_FORMATION' if manager else 'LTXT_CONSUMABLES_PLAYER_FORMATION'
        name = text[key].replace('\n', ' ') + ' ' + formation
        desc = text['FCC_CU_Arena_help_4' if manager else 'FUT_CONSUMABLE_FORMATIONMOD']
    tier = 'BRONZE'
    if row['rating'] >= 75:
        tier = 'GOLD'
    elif row['rating'] >= 65:
        tier = 'SILVER'
    rarity = 'RARE' if row['weightrare'] > 0 else 'COMMON'
    return {'NAME': name, 'DESC': desc, 'SHORT': f'1 ITEM\n{tier}\n{rarity}'}
