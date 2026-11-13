"""User-approved one-player tier-special prizes; no reward delivery here."""

import hashlib


SELECTION = "reviewed_tier_special_v1"
DEFINITIONS = {
    "revival_bronze_special_reward_v1": "bronze",
    "revival_silver_special_reward_v1": "silver",
}


def validate_definition(key, rule):
    tier = DEFINITIONS.get(key)
    expected = {
        "provenance": "revival_policy",
        "name": f"{tier.title()} Special Pack" if tier else "",
        "quality": tier,
        "item_family": "player",
        "item_count": 1,
        "minimum_rare": 1,
        "selection": SELECTION,
        "special_pool": "reviewed_all_admitted",
        "new_player_fitness": 99,
        "new_player_formation": "seeded_random_supported",
    }
    if (
        tier is None or rule != expected
        or any(type(rule[key]) is not type(value) for key, value in expected.items())
    ):
        raise ValueError("Invalid single-special tournament prize definition")


def select_pulls(definition, catalog_id, rule, *, private_identity_version=None):
    from .local_packs import PlayerPull
    from .reconstructed_specials import reviewed_pool

    validate_definition(definition, rule)
    if private_identity_version not in (None, "private_pack_identity_v2"):
        raise ValueError("Unknown pack identity version")
    limit = 0x7FFFFFFFFFFFFFFE if private_identity_version else 65535
    if type(catalog_id) is not int or not 30001 <= catalog_id <= limit:
        raise ValueError("Full unopened entitlement identity required")
    pool = reviewed_pool(rule["quality"])
    if not pool:
        raise ValueError("No admitted specials for this tier")

    def rank(card):
        source = f"{SELECTION}:{definition}:{catalog_id}:{card.record_id}"
        return hashlib.sha256(source.encode()).digest()

    chosen = min(pool, key=rank)
    return (PlayerPull(
        chosen.base_resource_id,
        chosen.record_id,
        chosen.pack_eligibility["base_rare"],
        chosen.pack_eligibility["base_quality"],
    ),)
