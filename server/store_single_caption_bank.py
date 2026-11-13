"""Append-only caption layout for isolated specific-card Store certification.

The original 19 blocks retain their offsets and capacity. No transactions or
authentication metadata are stored here; native_pack_sessions still owns them.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

PATH = Path(__file__).parent / "policy/store-single-caption-bank-v1.json"
VERSION = "native_pack_bank_store_singles_v1"
_CACHE = {}


def _validated(raw):
    digest = hashlib.sha256(raw).hexdigest()
    if digest in _CACHE:
        return _CACHE[digest]
    value = json.loads(raw)
    expected = {
        "version", "classification", "default_enabled", "first_wire_id",
        "maximum_end_exclusive", "legacy_slots", "single_slots",
        "legacy_definitions", "single_definitions",
    }
    if (
        type(value) is not dict or set(value) != expected
        or value["version"] != VERSION or value["classification"] != "revival_policy"
        or value["default_enabled"] is not False
        or any(type(value[k]) is not int or value[k] != v for k, v in (
            ("first_wire_id", 17000), ("maximum_end_exclusive", 30001),
            ("legacy_slots", 128), ("single_slots", 64),
        ))
    ):
        raise ValueError("Invalid append-only single-card caption profile")
    legacy = value["legacy_definitions"]
    singles = value["single_definitions"]
    if (
        type(legacy) is not list or len(legacy) != 19
        or type(singles) is not list or len(singles) != 115
        or any(type(d) is not str or not d.startswith("revival_") for d in legacy + singles)
        or len(set(legacy + singles)) != len(legacy + singles)
    ):
        raise ValueError("Invalid caption definition identities")
    from .pack_family_split import catalog
    from .tournament_reward_policy import allowed_pack_definitions
    from .store_single_consumables import definition_key, offer_index
    old = sorted({p["definition"] for p in catalog()["products"]})
    old += sorted(allowed_pack_definitions() - set(old))
    new = [definition_key(rid) for rid in sorted(offer_index())]
    if legacy != old or singles != new:
        raise ValueError("Caption profile must preserve the exact legacy order and supported singles")
    layout = {}
    first = value["first_wire_id"]
    for definitions, count in ((legacy, value["legacy_slots"]), (singles, value["single_slots"])):
        for definition in definitions:
            layout[definition] = (first, count)
            first += count
    if first > value["maximum_end_exclusive"]:
        raise ValueError("Single-card caption bank exceeds native namespace")
    result = {"policy": value, "layout": layout, "sha256": digest, "end_exclusive": first}
    if len(_CACHE) >= 8:
        _CACHE.clear()
    _CACHE[digest] = result
    return result


def profile(path=PATH):
    return deepcopy(_validated(Path(path).read_bytes()))


def bank():
    return {"version": VERSION, "profile_sha256": profile()["sha256"]}


def layout():
    return profile()["layout"]
