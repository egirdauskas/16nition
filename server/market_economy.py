"""Offline Transfer Market economy (MARKET-006): small, configurable, pure.

Implements the user's design direction (reports/market/design-2026-11-03.md):
separate valuation, demand and supply; linear cumulative sale probability;
bounded mispricing. Numbers come from a versioned placeholder policy and are
NOT approved values. Every random draw is seeded from stable identities, so a
restart can never reroll an outcome. Nothing here touches an account.
"""

import copy
import hashlib
import math
import json
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / 'server/policy/market-economy-v0.json'
POLICY_V1_PATH = ROOT / 'server/policy/market-economy-v1.json'
POLICY_V2_PATH = ROOT / 'server/policy/market-economy-v2.json'
VERSIONS = {'market_economy_v0', 'market_economy_v1', 'market_economy_v2'}
# The policy the running backend was configured with (market_protocol.configure);
# every pricing call without an explicit path uses it.
ACTIVE_PATH = POLICY_PATH
_POLICY_CACHE = {}


def use_policy(path):
    """Select the configured policy file for all later pricing calls."""
    global ACTIVE_PATH
    load_policy(path)
    ACTIVE_PATH = Path(path)


def load_policy(path=None):
    raw = Path(path or ACTIVE_PATH).read_bytes()
    key = hashlib.sha256(raw).digest()
    if key not in _POLICY_CACHE:
        value = json.loads(raw)
        if value.get('version') not in VERSIONS or value.get('default_enabled') is not False:
            raise ValueError('Unsupported market economy policy')
        if len(_POLICY_CACHE) > 4:
            _POLICY_CACHE.clear()
        _POLICY_CACHE[key] = value
    return copy.deepcopy(_POLICY_CACHE[key])


def items_enabled(policy=None):
    """Non-player trading exists only in policies with an `items` section (v1+)."""
    return 'items' in (policy or load_policy())


def rng(*parts):
    """Deterministic generator for one named decision."""
    seed = hashlib.sha256(':'.join(str(p) for p in parts).encode()).digest()
    return random.Random(int.from_bytes(seed[:8], 'big'))


@dataclass(frozen=True)
class CardFacts:
    resource_id: int
    rating: int
    quality: str          # bronze / silver / gold
    rare: bool
    special: bool
    position: str
    pace: int
    league: int
    nation: int
    skill_stars: int
    base_rating: int | None = None   # the regular card's rating (specials)


@lru_cache(maxsize=1)
def _league_by_team():
    from .club_player_search import content_filters
    _, _, leagues = content_filters()
    return {team: league for league, teams in leagues.items() for team in teams}


@lru_cache(maxsize=4096)
def facts(resource_id, special_version_id=None):
    from .card_pool import card_index
    from .local_content_source import attributes_for, position_for
    from .tournament_starter_facts import player_facts

    card = card_index()[resource_id]
    nation, skill_code = player_facts(card.player_id)
    rating, position, pace = card.rating, position_for(resource_id), attributes_for(resource_id)[0]
    if special_version_id is not None:
        from .reconstructed_specials import version
        special = version(special_version_id)
        rating, position, pace = special.rating, special.position, special.attributes[0]
    return CardFacts(
        resource_id=resource_id, rating=rating, quality=card.quality, rare=bool(card.rare),
        special=special_version_id is not None, position=position, pace=pace,
        league=_league_by_team().get(card.team_id, 0), nation=nation, skill_stars=skill_code + 1,
        base_rating=card.rating,
    )


def round_price(value, policy=None):
    """Clamp to the price range and round down to the market increment."""
    policy = policy or load_policy()
    price = policy['price']
    value = max(price['minimum'], min(price['maximum'], int(value)))
    for ceiling, step in price['increments']:
        if value < ceiling:
            return max(price['minimum'], value - value % step)
    return value


def card_minimum(card, policy=None):
    """Lowest price this card may trade at.

    The quality/rarity floor, and never below the card's quick-sell value
    (rounded up to a valid market price), so a listing can't undercut the bin.
    """
    if isinstance(card, ItemFacts):
        return item_minimum(card, policy)
    from .quick_sell_policy import player_coins

    policy = policy or load_policy()
    price = policy['price']
    category = 'special' if card.special else 'rare' if card.rare else 'common'
    floor = price['minimum']
    if not card.special:
        floor = price['card_minimum'][card.quality][category]
    return max(floor, round_price_up(player_coins(card.rating, category), policy))


def round_price_up(value, policy=None):
    """Smallest valid market price at or above `value`."""
    price = round_price(value, policy)
    return price if price >= value else next_bid(price, policy)


def next_bid(current, policy=None):
    """Smallest valid bid strictly above `current`."""
    policy = policy or load_policy()
    for ceiling, step in policy['price']['increments']:
        if current < ceiling:
            return round_price(current - current % step + step, policy)
    return current


def league_bonus(card, policy=None):
    """Per-league percent multipliers, or None outside the bonus leagues."""
    policy = policy or load_policy()
    return policy['league_bonus'].get(str(card.league))


def card_maximum(card, policy=None):
    """Highest price this card may trade at (non-special bronze/silver cap)."""
    if isinstance(card, ItemFacts):
        return item_maximum(card, policy)
    policy = policy or load_policy()
    price = policy['price']
    if card.special:
        if is_superstar(card, policy):
            return price['maximum']
        return price['special_maximum']
    return price['card_maximum'].get(card.quality, price['maximum'])


def is_superstar(card, policy=None):
    """A card whose regular version is rated superstar_base_rating+ (Messi, Ronaldo)."""
    policy = policy or load_policy()
    base = card.base_rating if card.base_rating is not None else card.rating
    return base >= policy['price']['superstar_base_rating']


def pace_premium(card, starts_below_great, policy=None, growth_percent=None):
    """Position-relative pace multiplier with league factors; 1.0 when not fast enough.

    Pace counts relative to what is great for the card's position (80 for a
    CB, 90 for a fullback or winger). A bonus league multiplies the premium
    (never slow cards), and near-great pace in such a league earns a further
    combination bonus.
    """
    policy = policy or load_policy()
    rule = policy['low_tier_pace']
    great = rule['great_pace'].get(card.position)
    if great is None:
        return 1.0
    over = card.pace - (great - starts_below_great)
    if over <= 0:
        return 1.0
    growth = growth_percent or rule['growth_percent_per_point']
    value = (growth / 100) ** over
    bonus = league_bonus(card, policy)
    if bonus is not None:
        value = value * bonus['low_tier'] / 100
        if card.pace >= great - rule['combo']['within_great']:
            value = value * bonus['combo'] / 100
    return value


def low_tier_value(card, policy=None):
    """Below-81 price: the floor, lifted by position-relative pace.

    Golds take a share of the same silver's value, so silvers stay dearer
    (silver cups).
    """
    policy = policy or load_policy()
    floor = card_minimum(card, policy)
    rule = policy['low_tier_pace']
    if card.quality not in rule['qualities']:
        return floor
    multiplier = pace_premium(card, rule['premium_starts_below_great'], policy)
    if multiplier == 1.0:
        return floor
    rarity = 'rare' if card.rare else 'common'
    base = floor
    if card.quality == 'gold':
        base = policy['price']['card_minimum']['silver'][rarity]
    value = base * multiplier
    if card.quality == 'gold':
        value = value * rule['gold_percent_of_silver'] / 100
    return max(floor, round_price(value, policy))


def low_gold_value(card, policy=None):
    """Golds 75-80: the silver-share pace premium, or the near-great bonus on the floor."""
    policy = policy or load_policy()
    floor = card_minimum(card, policy)
    near = round_price(floor * pace_curve(card, policy), policy)
    return max(low_tier_value(card, policy), near)


def mid_gold_pace(card, policy=None):
    """Steep pace premium for a non-elite gold 81-85, or 1.0 outside that band."""
    policy = policy or load_policy()
    band = policy['low_tier_pace']['mid_gold']
    if card.special or not band['minimum_rating'] <= card.rating <= band['maximum_rating']:
        return 1.0
    return pace_premium(card, band['premium_starts_below_great'], policy)


def pace_curve(card, policy=None):
    """Position-relative pace bonus for 81+ cards (never a discount).

    Full bonus at the position's great pace (80 for a CB, 90 for a fullback or
    winger). Only non-elite golds 75-85 also get a ramped bonus in the five
    points below great, so a 75-pace CB beats a 40-pace one there.
    """
    policy = policy or load_policy()
    curve = policy['modifiers_percent']['pace_curve']
    great = policy['low_tier_pace']['great_pace'].get(card.position)
    if great is None:
        return 1.0
    full = curve['full_bonus_percent'] / 100
    if card.pace >= great:
        return full
    near = curve['near_great']
    below = great - card.pace
    if card.special or not near['minimum_rating'] <= card.rating <= near['maximum_rating']:
        return 1.0
    if below > near['within']:
        return 1.0
    start = near['start_percent'] / 100
    return start + (full - start) * (near['within'] - below) / near['within']


def special_percent(card, policy=None):
    """Special premium: only superstars (base 93+) get the rating-graded bonus."""
    policy = policy or load_policy()
    price = policy['price']
    percent = 100
    if not is_superstar(card, policy):
        return percent
    for minimum, value in price['special_percent_by_rating']:
        if card.rating >= minimum:
            percent = value
    return percent


def reference_value(card, policy=None):
    """Fair price: quality/rarity floor below 81, convex by OVR from 81, plus modest modifiers."""
    if isinstance(card, ItemFacts):
        return item_reference_value(card, policy)
    policy = policy or load_policy()
    price = policy['price']
    # User direction 4 Nov 2026: below 81 a non-special card starts at its
    # quality/rarity floor; rating and the usual modifiers count from 81.
    if not card.special and card.rating < price['rating_priced_from']:
        if card.quality == 'gold':
            return low_gold_value(card, policy)
        return min(card_maximum(card, policy), low_tier_value(card, policy))
    convex = price['convex']
    curve = 0
    if card.rating >= convex['from_rating']:
        curve = convex['base'] * (convex['growth_percent'] / 100) ** (card.rating - convex['from_rating'])
    if card.special:
        # Specials keep their linear-by-OVR base at every rating.
        linear = price['linear']
        value = linear['base'] + max(0, card.rating - linear['from_rating']) * linear['per_point']
        value = max(value * price['quality_percent'][card.quality] / 100, curve)
    else:
        value = curve
    if card.rare:
        value = value * price['rare_percent'] / 100
    if card.special:
        value = value * special_percent(card, policy) / 100
    mods = policy['modifiers_percent']
    fast = mid_gold_pace(card, policy)
    if fast > 1.0:
        # Replaces the flat league and pace bonuses for fast golds 81-85.
        value = value * fast
    else:
        bonus = league_bonus(card, policy)
        if bonus is not None:
            value = value * bonus['high'] / 100
        value = value * pace_curve(card, policy)
    if card.nation in policy['top_nations']:
        value = value * mods['top_nation'] / 100
    skill = mods['skill_attackers']
    if card.position in skill['positions'] and card.skill_stars >= skill['minimum_stars']:
        value = value * skill['bonus'] / 100
    elite = mods['elite_attackers']
    # User direction: the top two (93+) keep their unboosted prices.
    if (card.position in elite['positions']
            and elite['minimum_rating'] <= card.rating <= elite['maximum_rating']):
        value = value * elite['bonus'] / 100
    if card.special and not is_superstar(card, policy):
        value = special_soft_cap(value, policy)
    value = max(card_minimum(card, policy), round_price(value, policy))
    return min(card_maximum(card, policy), value)


def special_soft_cap(value, policy=None):
    """Compress non-superstar specials above the knee toward the 5M ceiling, keeping order."""
    policy = policy or load_policy()
    knee = policy['price']['special_soft_cap_from']
    ceiling = policy['price']['special_maximum']
    if value <= knee:
        return value
    room = ceiling - knee
    return knee + room * (1 - math.exp(-(value - knee) / room))


def tier(card, policy=None):
    if isinstance(card, ItemFacts):
        return 'item'
    policy = policy or load_policy()
    if card.special:
        return 'special'
    if card.quality == 'gold' and card.rating >= policy['demand']['elite_rating']:
        return 'gold_elite'
    return card.quality


def demand_score(card, policy=None):
    """Percent chance (0-100) that a fairly priced listing finds a buyer."""
    if isinstance(card, ItemFacts):
        return (policy or load_policy())['items']['demand']
    policy = policy or load_policy()
    demand = policy['demand']
    level = tier(card, policy)
    if level == 'gold_elite':
        return demand['elite']
    return demand['gold' if level == 'gold' else level]


def sale_probability(card, asking_price, policy=None):
    """q: chance the listing sells before expiry (linear CDF over its duration)."""
    policy = policy or load_policy()
    sale = policy['sale']
    base = demand_score(card, policy) / 100
    ratio = 100 * asking_price / max(1, reference_value(card, policy))
    full, zero = sale['price_ratio_full_demand_percent'], sale['price_ratio_zero_demand_percent']
    if tier(card, policy) in ('gold_elite', 'special'):
        zero = 100 + (zero - 100) * 100 // sale['elite_sensitivity_multiplier_percent']
    if ratio <= full:
        factor = 1.0
    elif ratio >= zero:
        factor = 0.0
    else:
        factor = (zero - ratio) / (zero - full)
    return base * factor


def schedule_sale(listing_id, card, asking_price, duration, policy=None):
    """Decide once whether a bot buys, and when (skewed early; see policy sale.time_skew_power)."""
    q = sale_probability(card, asking_price, policy)
    draw = rng('sale', listing_id)
    if draw.random() >= q:
        return None
    # Most sales come early: P(sold by t) = q * (t/T)^(1/k), k = time_skew_power.
    rule = (policy or load_policy())['sale']
    when = duration * draw.random() ** rule.get('time_skew_power', 1)
    instant = rule.get('instant_below_percent')
    if instant is None:
        return int(when)
    # User direction 4 Nov 2026: the cheaper versus fair value, the faster a bot
    # buys; at or below `instant_below_percent` it buys almost at once.
    ratio = 100 * asking_price / max(1, reference_value(card, policy))
    low, high = rule['instant_seconds']
    if ratio <= instant:
        return min(duration - 1, low + int(draw.random() * (high - low)))
    if ratio < 100:
        when = when * (ratio - instant) / (100 - instant)
    return max(low, int(when))


def bot_listing_price(listing_id, card, policy=None):
    """(starting_bid, buy_now) with mostly-fair, occasionally cheap pricing."""
    policy = policy or load_policy()
    mis = policy['mispricing']
    draw = rng('list', listing_id)
    value = reference_value(card, policy)
    band = item_band(card, policy) if isinstance(card, ItemFacts) else None
    if band is not None:
        # User direction: bot listings fluctuate anywhere in the item's band.
        value = rng('band', listing_id).uniform(*band)
    scale = mis['special_scale_percent'] / 100 if card.special else 1.0
    roll = draw.random()
    if roll < mis['mistake_chance_per_mille'] / 1000 * scale:
        low, high = mis['mistake_discount_percent']
        factor = 1 - draw.uniform(low, high) / 100
    elif roll < (mis['mistake_chance_per_mille'] / 1000 + mis['bargain_chance_percent'] / 100) * scale:
        low, high = mis['bargain_discount_percent']
        # Bounded exponential: small discounts far likelier than large ones.
        span = high - low
        factor = 1 - (low + min(span, draw.expovariate(3 / span))) / 100
    else:
        low, high = mis['near_percent']
        factor = draw.uniform(low, high) / 100
    floor = card_minimum(card, policy)
    buy_now = max(floor, round_price(value * factor, policy))
    buy_now = min(card_maximum(card, policy), buy_now)
    start = max(floor, round_price(buy_now * draw.uniform(60, 90) / 100, policy))
    start = min(start, buy_now)
    if start == buy_now and next_bid(start, policy) <= card_maximum(card, policy):
        # Leave room for at least one bid below Buy Now (floor-priced cards).
        buy_now = next_bid(start, policy)
    return start, buy_now


def bot_reservation(actor_id, card, policy=None):
    """A bot's maximum price for one interaction."""
    policy = policy or load_policy()
    low, high = policy['bot_reservation_percent']
    value = reference_value(card, policy) * rng('reserve', actor_id).uniform(low, high) / 100
    value = max(card_minimum(card, policy), round_price(value, policy))
    return min(card_maximum(card, policy), value)


def fee(price, policy=None):
    policy = policy or load_policy()
    return price * policy['fee_percent'] // 100


# --- Non-player items (policy v1 `items`; user direction 4 Nov 2026) --------
#
# Club items (balls, badges, kits, stadiums) and managers trade both ways;
# consumables (training, healing, position change, formation) are sellable only:
# the stock search has no consumables category (1409/1413).

CONSUMABLE_FAMILIES = ('training', 'healing', 'position', 'formation')
ATTACKING = {'LW', 'RW', 'LF', 'RF', 'CAM', 'CF', 'ST'}
CENTRAL = {'CDM', 'CM', 'CAM', 'CF', 'ST'}
WINGBACK_PAIRS = {frozenset(('LWB', 'LB')), frozenset(('RWB', 'RB'))}
FOUR_BACK = {'f41212', 'f4231', 'f4222', 'f4312', 'f4321', 'f433', 'f4411', 'f442', 'f451'}


def position_group(source, destination):
    """User direction 4 Nov 2026: pricing group of a position-change card."""
    if frozenset((source, destination)) in WINGBACK_PAIRS:
        return 'wingback'
    if source in CENTRAL or destination in CENTRAL:
        rank = ('CDM', 'CM', 'CAM', 'CF', 'ST')
        forward = (source in rank and destination in ('CAM', 'CF', 'ST')
                   and rank.index(destination) > rank.index(source))
        return 'central_forward' if forward else 'central'
    if (source, destination) in (('RW', 'RF'), ('LW', 'LF')):
        return 'wing_to_forward'
    return 'wing'


@dataclass(frozen=True)
class ItemFacts:
    kind: str                  # ball/badge/kit/stadium/manager/training/healing/position/formation
    resource_id: int
    rating: int
    rare: bool
    nation: int = 0
    capacity: int = 0
    attacking: bool = False    # position change into a more attacking role
    group: str = ''            # position-change group / formation back line
    special: bool = False      # never: specials are players only


def consumable_family(subtype):
    from .local_consumables import INJURY_SUBTYPES
    if 51 <= subtype <= 57 or 61 <= subtype <= 67:
        return 'training'
    if 71 <= subtype <= 86 or 121 <= subtype <= 136:
        return 'formation'
    if 91 <= subtype <= 110:
        return 'position'
    if subtype in INJURY_SUBTYPES:
        return 'healing'
    return None


@lru_cache(maxsize=1)
def _stadium_capacity():
    from .local_content_source import DB, META
    from scripts.local_football_db import FootballDB
    db = FootballDB(DB, META)
    limit = db.table('fcc_stadium')['valid_count']
    return {r['carddbid']: r['capacity'] for r in db.rows('fcc_stadium', ['carddbid', 'capacity'])
            if r['row_index'] < limit}


@lru_cache(maxsize=4096)
def item_facts(kind, resource_id):
    """Facts for a tradeable non-player card; ValueError for untradeable kinds."""
    if kind == 'manager':
        from .local_content_source import manager_for
        row = manager_for(resource_id)
        return ItemFacts('manager', resource_id, row['value'], bool(row['rare']), nation=row['nation'])
    if kind in ('ball', 'badge', 'kit', 'stadium'):
        from .local_club_items import reference
        row = reference(kind, resource_id)
        capacity = _stadium_capacity().get(resource_id, 0) if kind == 'stadium' else 0
        return ItemFacts(kind, resource_id, row['rating'], bool(row['rare']), capacity=capacity)
    if kind == 'consumable':
        from .local_consumables import inventory_reference
        from .consumable_effects import POSITION_PAIRS
        from .local_content_source import POSITION_WIRE
        row = inventory_reference(resource_id)
        family = consumable_family(row['cardsubtype'])
        if family is None:
            raise ValueError('Consumable family is not tradeable')
        attacking = (family == 'position'
                     and POSITION_WIRE[POSITION_PAIRS[row['cardsubtype']][1]] in ATTACKING
                     and POSITION_WIRE[POSITION_PAIRS[row['cardsubtype']][0]] not in ATTACKING)
        group = ''
        if family == 'position':
            source, destination = (POSITION_WIRE[x] for x in POSITION_PAIRS[row['cardsubtype']])
            group = position_group(source, destination)
        elif family == 'formation':
            from .consumable_effects import MANAGER_FORMATIONS, PLAYER_FORMATIONS
            from .local_formations import FORMATIONS
            formation = {**PLAYER_FORMATIONS, **MANAGER_FORMATIONS}[row['cardsubtype']]
            group = 'four_back' if FORMATIONS[formation] in FOUR_BACK else 'other_back'
        return ItemFacts(family, resource_id, row['rating'], row['weightrare'] > 0, attacking=attacking, group=group)
    raise ValueError('Unknown item kind')


def item_quality(card):
    return 'gold' if card.rating >= 75 else 'silver' if card.rating >= 65 else 'bronze'


def item_quick_sell(card):
    """Quick-sell coins of an item under the existing approved quick-sell policies."""
    from .quick_sell_policy import club_policy, policy as quick_policy
    if card.kind == 'ball':
        return club_policy()[0]['ball_coins']
    if card.kind in ('badge', 'kit', 'stadium'):
        return club_policy()[0]['club_items'][item_quality(card)][int(card.rare)]
    if card.kind == 'manager':
        return 0
    brackets = quick_policy()[0]['consumables'][card.kind]
    quality = item_quality(card) if item_quality(card) in brackets else 'gold'
    return brackets[quality][int(card.rare)]


def item_reference_value(card, policy=None):
    policy = policy or load_policy()
    rule = policy['items']
    if card.kind == 'ball':
        value = rule['ball']
    elif card.kind in ('badge', 'kit') and 'club_bands' in rule:
        # User direction: no ranking inside a band; fair value is its midpoint.
        low, high = item_band(card, policy)
        value = (low + high) / 2
    elif card.kind == 'stadium' and 'named_band' in rule['stadium']:
        band = item_band(card, policy)
        value = rule['stadium']['generic'] if band is None else (band[0] + band[1]) / 2
    elif card.kind in ('badge', 'kit'):
        curve = rule['club_curve']
        value = curve['base'] * (curve['growth_percent'] / 100) ** max(0, card.rating - curve['from_value'])
        value = min(value, curve['cap'])
    elif card.kind == 'stadium':
        stadium = rule['stadium']
        if card.rating < stadium['famous_from_value']:
            value = stadium['generic']
        else:
            low, high = stadium['capacity_range']
            share = min(1, max(0, (card.capacity - low) / (high - low)))
            value = stadium['famous_low'] + share * (stadium['famous_high'] - stadium['famous_low'])
    elif card.kind == 'manager':
        manager = rule['manager']
        value = manager['base']
        for minimum, price in manager['by_rating']:
            if card.rating >= minimum:
                value = price
        if card.rare:
            value = value * manager['rare_percent'] / 100
        if card.nation in policy['top_nations']:
            value = value * manager['top_nation_percent'] / 100
    elif card.kind == 'position':
        position = rule['position']
        value = position['groups'][card.group] if 'groups' in position else position[
            'attacking' if card.attacking else 'base']
    elif card.kind == 'formation':
        formation = rule['formation']
        if isinstance(formation, dict):
            value = formation[card.group]['rare' if card.rare else 'common']
        else:
            value = formation
    else:
        value = rule[card.kind][item_quality(card)]
        if card.rare:
            value = value * rule['rare_percent'] / 100
    return min(item_maximum(card, policy), max(item_minimum(card, policy), round_price(value, policy)))


def item_band(card, policy=None):
    """(low, high) a bot item listing fluctuates within (policy v2), or None."""
    policy = policy or load_policy()
    rule = policy.get('items', {})
    if card.kind in ('badge', 'kit') and 'club_bands' in rule:
        band = next((b for b in rule['club_bands']['bands'] if card.rating >= b['from_value']),
                    rule['club_bands']['bands'][-1])
        return band['low'], band['high']
    if card.kind == 'stadium' and 'named_band' in rule.get('stadium', {}):
        if card.rating >= rule['stadium']['famous_from_value']:
            return tuple(rule['stadium']['named_band'])
    return None


def item_minimum(card, policy=None):
    """Item floor: the global minimum, never below its quick-sell value."""
    policy = policy or load_policy()
    return max(policy['price']['minimum'], round_price_up(item_quick_sell(card), policy))


def item_maximum(card, policy=None):
    policy = policy or load_policy()
    group = 'club' if card.kind in ('ball', 'badge', 'kit', 'stadium') else card.kind
    caps = policy['items']['listing_maximum']
    return caps.get(group, caps['consumable'])
