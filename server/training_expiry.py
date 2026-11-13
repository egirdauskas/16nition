"""One-game training lifetime in the existing native match recovery journal.

Only boosted members of the accepted squad are snapshotted. Initial
Play and genuine substitution packets determine participation. No extra record
is created for a match without training, and no separate transaction is used.
"""
import copy
import json

KEY = 'training_effects'
VERSION = 'one_game_training_v1'


def enabled(store):
    from .consumable_effects import features
    return 'training' in features(store)


def snapshot(store):
    if not enabled(store):
        return None
    state = store.load(1)
    roster = {slot.instance_id for slot in state.active_lineup}
    available = [[i.instance_id, i.training_resource_id] for i in state.owned_items
                 if i.instance_id in roster and i.training_resource_id is not None]
    if not available:
        return None
    return dict(version=VERSION, available=sorted(available), substitutions=[])


def ids(body):
    value = json.loads(body)
    if type(value) is not dict or set(value) != {'items'} or type(value['items']) is not list:
        raise ValueError('Training entry requires original Play items')
    result = []
    if not 1<=len(value['items'])<=23:
        raise ValueError('Invalid training participant vector')
    for item in value['items']:
        if type(item) is not dict or set(item) != {'id'} or type(item['id']) is not int or not 0<item['id']<=0x7fffffffffffffff:
            raise ValueError('Invalid training participant')
        result.append(item['id'])
    if len(result) != len(set(result)):
        raise ValueError('Duplicate training participant')
    return set(result)


def validate_source(source):
    marker = source.get(KEY)
    if marker is None:
        return
    if (type(marker) is not dict or set(marker) != {'version', 'available', 'substitutions'}
            or marker['version'] != VERSION or not source.get('atomic_match')
            or type(marker['available']) is not list or not 1 <= len(marker['available']) <= 23
            or type(marker['substitutions']) is not list or len(marker['substitutions']) > 23):
        raise ValueError('Invalid source-bound training snapshot')
    from .local_consumables import mapped_reference as reference
    from .consumable_effects import TRAINING_SUBTYPES
    seen = set()
    for pair in marker['available']:
        if (type(pair) is not list or len(pair) != 2 or any(type(v) is not int for v in pair)
                or not 0 < pair[0] <= 0x7fffffffffffffff or pair[0] in seen
                or reference(pair[1])['cardsubtype'] not in TRAINING_SUBTYPES):
            raise ValueError('Invalid training snapshot identity/resource')
        seen.add(pair[0])
    if marker['available'] != sorted(marker['available']):
        raise ValueError('Noncanonical training snapshot')
    entered = ids(bytes.fromhex(source['play_body_hex'])) if source.get('play_body_hex') else set()
    if marker['substitutions'] and not source.get('play_body_hex'):
        raise ValueError('Trained substitution before accepted initial Play')
    for raw in marker['substitutions']:
        group = ids(bytes.fromhex(raw))
        if not source.get('played_match') or not group&seen or group&seen<=entered:
            raise ValueError('Invalid/repeated trained substitution')
        entered.update(group)


def substitution(source, body):
    """Called only after existing PlayGame ownership/substitution validation."""
    validate_source(source)
    if KEY not in source:
        return
    group = ids(body)
    available = {i for i, _ in source[KEY]['available']}
    if not group&available or group&available<=participating(source):
        return
    source[KEY]['substitutions'].append(body.hex())
    validate_source(source)


def participating(source):
    validate_source(source)
    if KEY not in source or not source.get('play_body_hex'):
        return set()
    available = {i for i, _ in source[KEY]['available']}
    entered = ids(bytes.fromhex(source['play_body_hex']))
    for raw in source[KEY]['substitutions']:
        entered.update(ids(bytes.fromhex(raw)))
    return available & entered


def image(coordinator, source, *, before_raw=None):
    used = participating(source)
    if not used:
        return None
    raw = (coordinator.account / 'football.json').read_bytes() if before_raw is None else before_raw
    before = json.loads(raw)
    if before.get('persona_id')!=coordinator.identity()['persona_id']:
        raise ValueError('Training expiry belongs to another account')
    expected = dict(source[KEY]['available'])
    players = {p['instance_id']: p for p in before['owned_items']}
    if any(i not in players or players[i].get('training_resource_id') != expected[i] for i in used):
        raise ValueError('Training changed before its source match committed')
    after = copy.deepcopy(before)
    for player in after['owned_items']:
        if player['instance_id'] in used:
            player.pop('training_resource_id')
    from .native_season_completion import encode
    return dict(name='football.json', before=raw.hex(), after=encode(after).hex())


def before_image(images):
    found = next((i for i in images if i['name'] == 'football.json'), None)
    return bytes.fromhex(found['before']) if found is not None else None
