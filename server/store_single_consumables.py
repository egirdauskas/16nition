"""Prospective specific-card offers; no runtime or account admission.

Resources and effect families come from supplied Mobile content. Prices are
approved revival policy. This index is not a native Store product certificate.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .consumable_effects import (
    MANAGER_FORMATIONS, PLAYER_FORMATIONS, POSITION_PAIRS,
)
from .local_consumables import (
    CROWD_FILTERED_POOL, INJURY_SUBTYPES, inventory_reference, pack_references,
)
from .market_economy import POLICY_V2_PATH, item_facts, item_quality
from .policy_memo import policy_memo

PATH = Path(__file__).parent / "policy/store-single-consumables-v1.json"
TIERS = ("bronze", "silver", "gold")
CATEGORIES = (
    "healing", "player_training", "goalkeeper_training", "player_position",
    "player_formation", "manager_formation",
)
_POLICY_CACHE = {}
_MARKET_CACHE = {}
_INDEX_CACHE = {}
SELECTION = "specific_supplied_consumable_v1"
FAMILY_NAMES = {
    "healing": "Player Healing",
    "player_training": "Player Training",
    "goalkeeper_training": "Goalkeeper Training",
    "player_position": "Player Position",
    "player_formation": "Player Formation",
    "manager_formation": "Manager Formation",
}
CATALOG_VERSION = "local_store_catalog_v7"
FIRST_SKU = 55000
# Archived group501/category vector in run755, matched to the original eight
# tiles; indices6/7 were also physically selected as Position516/Formation517.
CATEGORY_IDS = {
    "healing": 512,
    "player_training": 514,
    "goalkeeper_training": 515,
    "player_position": 516,
    "player_formation": 517,
    "manager_formation": 518,
}


def _positive_price(value):
    return type(value) is int and 0 < value <= 0x7fffffff


def _validated_policy(raw):
    key = hashlib.sha256(raw).digest()
    if key in _POLICY_CACHE:
        return _POLICY_CACHE[key]
    value = json.loads(raw)
    fields = {
        "version", "classification", "default_enabled", "quantity_per_offer",
        "authorization", "training", "healing", "position_and_formation",
        "supported_categories", "fitness_and_morale_offers_enabled",
        "stock_certification",
    }
    if (
        type(value) is not dict or set(value) != fields
        or value["version"] != "store_single_consumables_v1"
        or value["classification"] != "revival_policy"
        or value["default_enabled"] is not False
        or type(value["quantity_per_offer"]) is not int
        or value["quantity_per_offer"] != 1
        or value["supported_categories"] != list(CATEGORIES)
        or value["fitness_and_morale_offers_enabled"] is not False
        or any(type(value[k]) is not str or not value[k] for k in (
            "authorization", "stock_certification",
        ))
    ):
        raise ValueError("Invalid single-consumable Store policy")
    training = value["training"]
    if (
        type(training) is not dict or set(training) != {
            "player_and_goalkeeper_same_prices", "duration_matches", "coin_prices",
        }
        or training["player_and_goalkeeper_same_prices"] is not True
        or type(training["duration_matches"]) is not int
        or training["duration_matches"] != 1
        or type(training["coin_prices"]) is not dict
        or set(training["coin_prices"]) != set(TIERS)
    ):
        raise ValueError("Invalid single-card training policy")
    for row in training["coin_prices"].values():
        if (
            type(row) is not dict or set(row) != {"common", "rare"}
            or not all(_positive_price(v) for v in row.values())
            or row["rare"] != 2 * row["common"]
        ):
            raise ValueError("Rare training must cost twice common training")
    healing = value["healing"]
    if (
        type(healing) is not dict or set(healing) != {"coin_prices", "authorization"}
        or type(healing["authorization"]) is not str or not healing["authorization"]
        or type(healing["coin_prices"]) is not dict
        or set(healing["coin_prices"]) != set(TIERS)
        or not all(_positive_price(v) for v in healing["coin_prices"].values())
    ):
        raise ValueError("Invalid single-card healing policy")
    modifiers = value["position_and_formation"]
    if (
        type(modifiers) is not dict or set(modifiers) != {
            "price_policy", "sections", "authorization",
        }
        or modifiers["price_policy"] != "server/policy/market-economy-v2.json"
        or modifiers["sections"] != ["items.position", "items.formation"]
        or type(modifiers["authorization"]) is not str or not modifiers["authorization"]
    ):
        raise ValueError("Single-card modifiers require approved v2 price targets")
    if len(_POLICY_CACHE) >= 8:
        _POLICY_CACHE.clear()
    _POLICY_CACHE[key] = value
    return value


def policy(path=PATH):
    return deepcopy(_validated_policy(Path(path).read_bytes()))


def category_for(subtype):
    if type(subtype) is not int:
        raise ValueError("Invalid consumable subtype")
    # Original target validator: subtype < 60 requires a goalkeeper. See
    # local_consumables.validate_training_target and frozen run314 evidence.
    if 51 <= subtype <= 57:
        return "goalkeeper_training"
    if 61 <= subtype <= 67:
        return "player_training"
    if subtype in PLAYER_FORMATIONS:
        return "player_formation"
    if subtype in MANAGER_FORMATIONS:
        return "manager_formation"
    if subtype in POSITION_PAIRS:
        return "player_position"
    if subtype in INJURY_SUBTYPES:
        return "healing"
    raise ValueError("Consumable has no supported individual Store offer")


def _modifier_prices(raw):
    key = hashlib.sha256(raw).digest()
    if key in _MARKET_CACHE:
        return _MARKET_CACHE[key]
    value = json.loads(raw)
    if (
        type(value) is not dict or value.get("version") != "market_economy_v2"
        or value.get("default_enabled") is not False
        or type(value.get("items")) is not dict
    ):
        raise ValueError("Single-card modifiers require market policy v2 targets")
    items = value["items"]
    position = items.get("position")
    formation = items.get("formation")
    groups = {"wingback", "central", "central_forward", "wing_to_forward", "wing"}
    if (
        type(position) is not dict or type(position.get("groups")) is not dict
        or set(position["groups"]) != groups
        or not all(_positive_price(v) for v in position["groups"].values())
        or type(formation) is not dict
    ):
        raise ValueError("Invalid approved position price targets")
    for group in ("four_back", "other_back"):
        row = formation.get(group)
        if (
            type(row) is not dict or set(row) != {"common", "rare"}
            or not all(_positive_price(v) for v in row.values())
        ):
            raise ValueError("Invalid approved formation price targets")
    result = {
        "position": position["groups"],
        "formation": {g: formation[g] for g in ("four_back", "other_back")},
    }
    if len(_MARKET_CACHE) >= 8:
        _MARKET_CACHE.clear()
    _MARKET_CACHE[key] = result
    return result


def offer_index(policy_path=PATH, modifier_policy_path=POLICY_V2_PATH):
    """Return card references/prices, never wire IDs, entitlements or accounts.

    Market admission and bot price variation do not affect fixed Store prices.
    Native category numbers and caption allocation need separate certification.
    """
    raw = Path(policy_path).read_bytes()
    modifier_raw = Path(modifier_policy_path).read_bytes()
    key = (hashlib.sha256(raw).digest(), hashlib.sha256(modifier_raw).digest())
    if key in _INDEX_CACHE:
        return deepcopy(_INDEX_CACHE[key])
    config = _validated_policy(raw)
    modifiers = _modifier_prices(modifier_raw)
    result = {}
    for resource_id, row in sorted(pack_references(CROWD_FILTERED_POOL).items()):
        try:
            category = category_for(row["cardsubtype"])
        except ValueError:
            continue
        facts = item_facts("consumable", resource_id)
        tier = item_quality(facts)
        rarity = "rare" if facts.rare else "common"
        if category in ("player_training", "goalkeeper_training"):
            price = config["training"]["coin_prices"][tier][rarity]
        elif category == "healing":
            price = config["healing"]["coin_prices"][tier]
        elif category == "player_position":
            price = modifiers["position"][facts.group]
        else:
            price = modifiers["formation"][facts.group][rarity]
        result[resource_id] = {
            "resource_id": resource_id,
            "subtype": row["cardsubtype"],
            "category": category,
            "quality": tier,
            "rare": facts.rare,
            "quantity": 1,
            "coin_price": price,
        }
    if not result or set(r["category"] for r in result.values()) != set(CATEGORIES):
        raise ValueError("Incomplete supplied single-consumable Store index")
    if len(_INDEX_CACHE) >= 8:
        _INDEX_CACHE.clear()
    _INDEX_CACHE[key] = result
    return deepcopy(result)


def offer(resource_id, **paths):
    if type(resource_id) is not int:
        raise ValueError("Invalid single-card resource identity")
    result = offer_index(**paths).get(resource_id)
    if result is None:
        raise ValueError("Resource has no supported individual Store offer")
    return result


def definition_key(resource_id):
    if type(resource_id) is not int:
        raise ValueError("Invalid single-card resource identity")
    category_for(inventory_reference(resource_id)["cardsubtype"])
    return f"revival_single_consumable_{resource_id}_v1"


def pack_definition(resource_id):
    """Immutable exact resource, separate from prices and runtime catalog IDs.

    Names here identify the family only. Specific native card captions/artwork
    remain a separate presentation task; no historical EA SKU is asserted.
    """
    definition_key(resource_id)
    row = inventory_reference(resource_id)
    category = category_for(row["cardsubtype"])
    tier = "bronze"
    if row["rating"] >= 75:
        tier = "gold"
    elif row["rating"] >= 65:
        tier = "silver"
    return {
        "provenance": "revival_policy",
        "name": FAMILY_NAMES[category],
        "quality": tier,
        "item_family": "consumable",
        "item_count": 1,
        "minimum_rare": int(row["weightrare"] > 0),
        "selection": SELECTION,
        "resource_id": resource_id,
    }


def validate_definition(key, rule):
    resource_id = rule.get("resource_id")
    expected_key = definition_key(resource_id)
    expected = pack_definition(resource_id)
    if (
        key != expected_key or rule != expected
        or any(type(rule[k]) is not type(v) for k, v in expected.items())
    ):
        raise ValueError("Specific consumable definition must preserve its supplied card")


def select_resource(rule, catalog_id, *, private_identity_version=None):
    from .native_pack_sessions import PRIVATE_MAX, PRIVATE_VERSION
    if private_identity_version not in (None, PRIVATE_VERSION):
        raise ValueError("Unsupported specific-card identity version")
    maximum = PRIVATE_MAX if private_identity_version == PRIVATE_VERSION else 65535
    if type(catalog_id) is not int or not 30001 <= catalog_id <= maximum:
        raise ValueError("Full entitlement identity required for a specific card")
    return (rule["resource_id"],)


@policy_memo
def catalog():
    """Prospective coin-only singles; all existing products remain identical.

    These are local service SKUs, not claimed EA identifiers. Session aliases
    remain allocated independently by the guarded append-only caption profile.
    """
    from .pack_family_split import catalog as previous
    value = previous()
    value["version"] = CATALOG_VERSION
    existing = {row["product_id"] for row in value["products"]}
    for n, (resource_id, row) in enumerate(offer_index().items()):
        sku = FIRST_SKU + n
        if sku in existing or sku > 65535:
            raise ValueError("Single-consumable Store SKU collision")
        value["products"].append({
            "product_id": sku,
            "definition": definition_key(resource_id),
            "provenance": "revival_policy",
            "coin_price": row["coin_price"],
            "repeatable": True,
            "purchase_limit": 1,
            "featured": False,
        })
    return value


def category_ids(definition):
    prefix = "revival_single_consumable_"
    suffix = "_v1"
    if (
        type(definition) is not str or not definition.startswith(prefix)
        or not definition.endswith(suffix)
    ):
        raise ValueError("Unknown specific-card definition")
    resource_id = int(definition[len(prefix):-len(suffix)])
    if definition != definition_key(resource_id):
        raise ValueError("Noncanonical specific-card definition")
    row = inventory_reference(resource_id)
    return [CATEGORY_IDS[category_for(row["cardsubtype"])]]
