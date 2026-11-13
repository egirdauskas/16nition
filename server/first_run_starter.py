"""FIRST-002 starter club for a new first-run account (revival_policy).

The composition is the user's approved policy (first-run-starter-v1.json, 8 Nov
2026): 23 non-rare base players filling the stock default 4-4-2 (one player
from the favourite club, preferring gold), a random bronze manager and the
favourite club's badge, kits and stadium. Players and items are references to
supplied database rows only; no names, ratings or assets are stored.

The draw is random per account, from a seed recorded in the grant receipt, so
the same receipt always reproduces the same club. grant() writes football.json
and the receipt once; later calls return the stored receipt unchanged.
"""
import hashlib
import json
import os
import random
import secrets
import time
from pathlib import Path

POLICY_PATH = Path(__file__).parent / 'policy/first-run-starter-v1.json'
RECEIPT = 'first-run-grant.json'
RECEIPT_VERSION = 'first_run_grant_v1'
FIRST_INSTANCE = 4294967297  # Same first local instance ID as every account.

# Stock default 4-4-2 roles by squad slot (preferred position IDs, best first),
# as used by the development seed. Slots 18-22 are reserves of any role.
ROLE_PREFERENCES = (
    (0,), (3, 2, 8, 7, 5), (5,), (5,), (7, 8, 3, 2, 5), (12, 23), (14, 10, 18),
    (14, 10, 18), (16, 27), (25, 21, 23, 27), (25, 21, 23, 27),
    (0,), (5, 7, 8, 3), (5, 7, 8, 3), (14, 10, 18), (16, 27), (12, 23), (25, 21, 27),
)
SQUAD_SIZE = 23
STARTERS = 11


def sha(data):
    return hashlib.sha256(data).hexdigest()


def policy():
    raw = POLICY_PATH.read_bytes()
    value = json.loads(raw)
    if value.get('version') != 'first_run_starter_v1':
        raise ValueError('Unknown first-run starter policy')
    starting = value['starting']
    bench = value['bench']
    if (starting.get('favourite_club') != 1 or sum(starting.values()) != STARTERS
            or sum(bench.values()) != SQUAD_SIZE - STARTERS):
        raise ValueError('Starter policy does not fill the stock squad')
    return value, sha(raw)


def player_pool(rare_values):
    """Base, lookup-supported player cards by quality (supplied rows only)."""
    from .card_pool import card_index
    pool = {'gold': [], 'silver': [], 'bronze': []}
    for card in card_index().values():
        if card.lookup_supported and card.variant == 'base' and card.packed_class == 7:
            if card.rare in rare_values:
                pool[card.quality].append(card)
    for cards in pool.values():
        cards.sort(key=lambda c: c.resource_id)
    return pool


def favourite_player(rng, team_id, order):
    from .card_pool import card_index
    club = [c for c in card_index().values()
            if c.team_id == team_id and c.lookup_supported and c.variant == 'base' and c.packed_class == 7]
    for quality in order:
        candidates = sorted((c for c in club if c.quality == quality), key=lambda c: c.resource_id)
        if candidates:
            return rng.choice(candidates)
    raise ValueError('Favourite club has no supplied player card')


def slot_for(card, free):
    """First free slot whose role accepts the card's preferred position."""
    for slot in free:
        if slot < len(ROLE_PREFERENCES) and card.preferred_position in ROLE_PREFERENCES[slot]:
            return slot
    return free[-1]


def draw_squad(rng, value, team_id):
    pool = player_pool(set(value['player_rare']))
    chosen = {}
    used_players = set()
    favourite = favourite_player(rng, team_id, value['favourite_club_quality_order'])
    free = list(range(STARTERS))
    slot = slot_for(favourite, free)
    if slot >= STARTERS:
        slot = free[0]
    chosen[slot] = favourite
    used_players.add(favourite.player_id)
    plan = []
    for group, slots in (('starting', range(STARTERS)), ('bench', range(STARTERS, SQUAD_SIZE))):
        qualities = [q for q, n in value[group].items() if q != 'favourite_club' for _ in range(n)]
        rng.shuffle(qualities)
        open_slots = [s for s in slots if s not in chosen]
        plan.extend(zip(open_slots, qualities))
    for slot, quality in plan:
        roles = ROLE_PREFERENCES[slot] if slot < len(ROLE_PREFERENCES) else None
        available = [c for c in pool[quality] if c.player_id not in used_players]
        card = None
        if roles is not None:
            for role in roles:
                matching = [c for c in available if c.preferred_position == role]
                if matching:
                    card = rng.choice(matching)
                    break
        if card is None:
            outfield = [c for c in available if c.preferred_position != 0] if roles != (0,) else available
            card = rng.choice(outfield)
        chosen[slot] = card
        used_players.add(card.player_id)
    return [chosen[s] for s in range(SQUAD_SIZE)]


def draw_manager(rng, quality):
    from .local_content_source import managers
    limit = {'bronze': (0, 64), 'silver': (65, 74), 'gold': (75, 99)}[quality]
    candidates = sorted(r['carddbid'] for r in managers().values() if limit[0] <= r['value'] <= limit[1])
    if not candidates:
        raise ValueError('No supplied manager of the starter quality')
    return rng.choice(candidates)


def club_items(team_id):
    """Favourite club badge, home/away kits and stadium (absent rows omitted)."""
    from .local_content_source import badges, club_resources
    from scripts.local_football_db import FootballDB
    from .local_content_source import DB, META
    badge = min((rid for rid, (team, _) in badges().items() if team == team_id), default=None)
    kits = sorted((row for (kind, _), row in club_resources().items()
                   if kind == 'kit' and row['teamid'] == team_id and row['category'] in (2, 3)),
                  key=lambda row: (row['category'], row['carddbid']))
    kits = [next(r for r in kits if r['category'] == c) for c in (2, 3) if any(r['category'] == c for r in kits)]
    db = FootballDB(DB, META)
    link = next((r for r in db.rows('teamstadiumlinks', ['teamid', 'stadiumid']) if r['teamid'] == team_id), None)
    stadium = None
    if link is not None:
        stadium = min((row['carddbid'] for (kind, _), row in club_resources().items()
                       if kind == 'stadium' and row['stadiumid'] == link['stadiumid']), default=None)
    items = [('kit', row['carddbid']) for row in kits]
    if stadium is not None:
        items.append(('stadium', stadium))
    return badge, items


def build(seed, team_id):
    """Deterministic starter club for a recorded seed and favourite team."""
    from .local_football import (FootballState, OwnedBadgeItem, OwnedClubItem, OwnedManagerItem,
                                 OwnedPlayerItem, SquadSlot)
    value, policy_sha = policy()
    rng = random.Random(seed)
    squad = draw_squad(rng, value, team_id)
    manager = draw_manager(rng, value['manager_quality'])
    badge, items = club_items(team_id)
    next_id = FIRST_INSTANCE
    players = []
    for card in squad:
        players.append(OwnedPlayerItem(next_id, card.resource_id, value['fitness']))
        next_id += 1
    lineup = tuple(SquadSlot(index, item.instance_id) for index, item in enumerate(players))
    owned_manager = OwnedManagerItem(next_id, manager)
    next_id += 1
    active_badge = None
    if badge is not None:
        active_badge = OwnedBadgeItem(next_id, badge)
        next_id += 1
    active_items = []
    for kind, resource in items:
        active_items.append(OwnedClubItem(next_id, resource, kind))
        next_id += 1
    state = FootballState(1, tuple(players), lineup, active_badge, tuple(active_items),
                          next_instance_id=next_id, active_manager=owned_manager)
    summary = {
        'players': [c.resource_id for c in squad],
        'favourite_player': squad[[c.team_id == team_id for c in squad].index(True)].resource_id,
        'manager': manager, 'badge': badge, 'club_items': [list(i) for i in items],
    }
    return state, summary, policy_sha


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.new')
    with temporary.open('w') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def is_empty(state):
    """The fresh-account football state: persona only, nothing owned."""
    from .local_football import FootballState
    return state == FootballState(state.persona_id)


def granted(account):
    path = Path(account) / RECEIPT
    if not path.exists():
        return None
    value = json.loads(path.read_bytes())
    if value.get('version') != RECEIPT_VERSION:
        raise ValueError('Unknown first-run grant receipt')
    return value


def grant(account, team_id, seed=None):
    """Create the starter club once (football.json, then the receipt)."""
    from .local_content import ContentCatalog
    from .local_football import FootballStore
    account = Path(account)
    football = account / 'football.json'
    store = FootballStore(football, ContentCatalog(account / 'content.json'))
    receipt = granted(account)
    if receipt is None:
        if football.exists() and not is_empty(store.load(1)):
            raise ValueError('Football state exists without a first-run grant receipt')
        seed = seed if seed is not None else secrets.token_hex(16)
        _, summary, policy_sha = build(seed, team_id)
        # Receipt first: an interrupted grant is rebuilt from the same seed.
        receipt = {'version': RECEIPT_VERSION, 'utc': int(time.time()), 'seed': seed,
                   'favourite_team_id': team_id, 'policy_sha256': policy_sha, **summary}
        write_json(account / RECEIPT, receipt)
    elif receipt['favourite_team_id'] != team_id:
        raise ValueError('Starter already granted for another favourite club')
    if not football.exists() or is_empty(store.load(1)):
        state, summary, _ = build(receipt['seed'], receipt['favourite_team_id'])
        if summary['players'] != receipt['players'] or summary['manager'] != receipt['manager']:
            raise ValueError('Starter rebuild differs from its receipt')
        store.save(state)
    return receipt
