"""FIRST-002 deterministic supplied starter selection; explicit revival policy."""
import hashlib

from .local_football import (
    FootballState,
    ItemLocation,
    OwnedClubItem,
    OwnedManagerItem,
    OwnedPlayerItem,
    SquadSlot,
)
from .local_packs import reviewed_player_pool
from .local_content_source import managers
from .pack_special_rates import probabilities, pick, rates_for


# Ordered role preferences copied from seed_development_account.py.
_ROLES = (
    (0,), (3, 2, 8, 7, 5), (5,), (5,), (7, 8, 3, 2, 5),
    (12, 23), (14, 10, 18), (14, 10, 18), (16, 27),
    (25, 21, 23, 27), (25, 21, 23, 27), (0,),
    (5, 7, 8, 3), (5, 7, 8, 3), (14, 10, 18), (16, 27),
    (12, 23), (25, 21, 27),
)
_SPECIAL_RATE_RULE = {"selection": "reviewed_specials_sha256_without_replacement"}
# User-approved new-club default, 9 Nov 2026. Supplied fcc_stadium row14:
# Waldstadion (Fussballstadion), stadium/asset176. Existing clubs are not reseeded.
STARTING_STADIUM_RESOURCE = 6200014


def _rank(seed, label, pull):
    value = f"first-run-roster-v1:{seed}:{label}:{pull.resource_id}:{pull.special_version_id or 'base'}"
    return hashlib.sha256(value.encode()).digest()


def _identity(pull, cards):
    return cards[pull.resource_id].player_id


def _draw_for_base(seed, label, base, tier_pool, already, cards, probability, position):
    options = [pull for pull in tier_pool
               if pull.base_rare == base.base_rare
               and (position is None or cards[pull.resource_id].preferred_position == position)]
    ordered = sorted(options, key=lambda pull: _rank(seed, label, pull))

    def usable(pull, chosen):
        return (_identity(pull, cards) not in already and
                all(_identity(other, cards) != _identity(pull, cards) for other in chosen))

    selected = pick(ordered, 1, probability, f"{seed}:{label}", usable)
    if len(selected) != 1:
        raise ValueError(f"No supported draw for {label}")
    already.add(_identity(selected[0], cards))
    return selected[0]


def _select(seed, label, quality, already, cards, eligible=None, base_rare=None):
    tier_pool = reviewed_player_pool(quality, families=None)
    ordinary = [pull for pull in tier_pool if pull.special_version_id is None]
    position = None
    if eligible is not None:
        position = next((pos for pos in eligible if any(
            cards[pull.resource_id].preferred_position == pos
            and _identity(pull, cards) not in already for pull in ordinary)), None)
        ordinary = [pull for pull in ordinary if cards[pull.resource_id].preferred_position == position]
    if base_rare is not None:
        ordinary = [pull for pull in ordinary if pull.base_rare == base_rare]
    ordinary = [pull for pull in ordinary if _identity(pull, cards) not in already]
    if not ordinary:
        raise ValueError(f"No eligible supplied ordinary {quality} base for {label}")
    base = min(ordinary, key=lambda pull: _rank(seed, f"base:{label}", pull))

    # The chance is calculated over the complete tier pool; role filtering only
    # limits which player's base card can fill this roster slot.
    rates = rates_for(_SPECIAL_RATE_RULE)
    chance = probabilities(tier_pool, rates)[quality, bool(base.base_rare)] if rates else 0
    return _draw_for_base(seed, label, base, tier_pool, already, cards, chance, position)


def starter_roster(seed: str, first_instance_id: int) -> FootballState:
    """Build the approved players/manager and one active supplied Waldstadion."""
    if not isinstance(seed, str) or not seed:
        raise ValueError("seed must be a nonempty string")
    if type(first_instance_id) is not int or first_instance_id <= 0:
        raise ValueError("first_instance_id must be a positive integer")

    from .card_pool import card_index
    cards = card_index()
    already = set()
    roster = [
        _select(seed, f"bronze-role-{slot}", "bronze", already, cards, role)
        for slot, role in enumerate(_ROLES)
    ]
    gold = _select(seed, "extra-gold", "gold", already, cards, None, base_rare=0)
    silver = [
        _select(seed, f"extra-silver-{slot}", "silver", already, cards, None)
        for slot in range(3)
    ]
    extra_items = [gold, *silver]

    # Preserve the previously approved random Bronze manager (8 Nov).
    manager_ids = {rid: row for rid, row in managers().items() if 0 <= row['value'] < 65}
    if not manager_ids:
        raise ValueError("No supplied supported manager cards")
    manager_resource = min(
        manager_ids,
        key=lambda resource: hashlib.sha256(
            f"first-run-manager-v1:{seed}:{resource}".encode()
        ).digest(),
    )
    manager_instance = first_instance_id + 22
    manager = OwnedManagerItem(manager_instance, manager_resource, formation_id=23)
    stadium_instance = manager_instance + 1
    stadium = OwnedClubItem(stadium_instance, STARTING_STADIUM_RESOURCE, 'stadium')

    pulls = roster + extra_items
    player_items = tuple(
        OwnedPlayerItem(
            first_instance_id + offset,
            pull.resource_id,
            fitness=99,
            morale=99,
            special_version_id=pull.special_version_id,
        )
        for offset, pull in enumerate(pulls)
    )
    # Stock slots 0–10 are the XI, 11–17 substitutes and 18–22 reserves.
    # Keep the four bonus players immediately available on the squad screen.
    lineup = tuple(
        SquadSlot(slot, item.instance_id)
        for slot, item in enumerate(player_items)
    )
    locations = tuple(ItemLocation(item.instance_id, "club") for item in player_items)
    locations += (ItemLocation(manager_instance, "club"),
                  ItemLocation(stadium_instance, "club"))
    return FootballState(
        persona_id=1,
        owned_items=player_items,
        active_lineup=lineup,
        formation_id=23,
        active_manager=manager,
        active_club_items=(stadium,),
        inventory_locations=locations,
        next_instance_id=stadium_instance + 1,
    )
