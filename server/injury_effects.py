"""Original injury fields and source-bound match persistence, disabled by default.

Wire injuryType strings come from01030764/table027aa8c8; games/type occupy
player+101/+100. Healing211..218 maps to native modifier type(subtype-211),
where7 is the all-injuries wildcard. Amounts come from supplied valid rows.
"""
import copy
from dataclasses import replace
import hashlib
import json
import re

TYPES = ('head', 'shoulder', 'arm', 'back', 'hip', 'leg', 'foot')
KEY = 'injury_effects'
VERSION = 'native_injury_effects_v1'


def validate_player(player):
    kind, games = player.injury_type, player.injury_games
    if kind is None and games is None:
        return
    if (kind not in (*TYPES, 'none') or type(games) is not int
            or not 0 <= games <= 255 or (kind == 'none') != (games == 0)):
        raise ValueError('Invalid native player injury')


def healing(player, resource):
    from .local_consumables import inventory_reference, INJURY_SUBTYPES
    validate_player(player)
    ref = inventory_reference(resource)
    subtype = ref['cardsubtype']
    if subtype not in INJURY_SUBTYPES:
        raise ValueError('Unsupported supplied injury-healing card')
    if player.injury_type in (None, 'none') or not player.injury_games:
        raise ValueError('Healing requires an injured player')
    modifier = subtype - 211
    if modifier != 7 and TYPES[modifier] != player.injury_type:
        raise ValueError('Healing card does not match player injury')
    amount = ref['amount']
    if type(amount) is not int or amount <= 0:
        raise ValueError('Invalid supplied healing amount')
    games = max(0, player.injury_games - amount)
    return replace(player, injury_type=player.injury_type if games else 'none', injury_games=games)


def signature(value):
    rows = sorted([p['instance_id'], p['injury_type'], p['injury_games']]
                  for p in value['owned_items'] if p.get('injury_games', 0))
    return hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()


def enabled(store):
    from .consumable_effects import features
    return 'healing' in features(store)


def snapshot(store):
    if not enabled(store):
        return None
    store.load(1)  # Preserve full domain validation before pinning current state.
    return dict(version=VERSION, before_sha256=signature(json.loads(store.path.read_bytes())))


def validate_source(source):
    if KEY not in source:
        return
    marker = source[KEY]
    if (type(marker) is not dict or set(marker) != {'version', 'before_sha256'}
            or marker['version'] != VERSION or not source.get('atomic_match')
            or not isinstance(marker['before_sha256'], str)
            or re.fullmatch('[0-9a-f]{64}', marker['before_sha256']) is None):
        raise ValueError('Invalid source-bound injury policy')


def native_condition(row):
    # Genuine233/234/237 End items omit zero games even when type remains leg.
    kind, games = row.get('injuryType', 'none'), row.get('injuryGames', 0)
    if (kind not in (*TYPES, 'none') or type(games) is not int or not 0 <= games <= 255
            or games and kind == 'none'):
        raise ValueError('Unmapped original match injury fields')
    return (kind, games) if games else ('none', 0)


def validate_end(source, body):
    if KEY not in source:
        return
    validate_source(source)
    for row in json.loads(body)['items']:
        native_condition(row)


def match_image(coordinator, source, *, before_raw=None):
    """Compose injury and training changes into the existing one Football image."""
    from .training_expiry import image as training_image
    validate_source(source)
    if KEY not in source:
        return training_image(coordinator, source, before_raw=before_raw)
    initial = (coordinator.account / 'football.json').read_bytes() if before_raw is None else before_raw
    before = json.loads(initial)
    store = coordinator.stores()[1]
    store.decode(before, coordinator.identity()['persona_id'])
    if signature(before) != source[KEY]['before_sha256']:
        raise ValueError('Injury state changed during accepted match')
    trained = training_image(coordinator, source, before_raw=initial)
    after = json.loads(bytes.fromhex(trained['after'])) if trained else copy.deepcopy(before)
    value = json.loads(bytes.fromhex(source['end_body_hex']))
    players = {p['instance_id']: p for p in after['owned_items']}
    seen = set()
    for row in value['items']:
        iid = row.get('id')
        if type(iid) is not int or iid in seen or iid not in players:
            raise ValueError('Invalid original injury item ownership')
        seen.add(iid)
        kind, games = native_condition(row)
        target = players[iid]
        # Healthy legacy rows retain their schema; no state is added per player
        # or per match unless the native producer actually reports an injury.
        if games or target.get('injury_type') is not None:
            target.update(injury_type=kind, injury_games=games)
    store.decode(after, coordinator.identity()['persona_id'])
    if after == before:
        return None
    from .native_season_completion import encode
    return dict(name='football.json', before=initial.hex(), after=encode(after).hex())
