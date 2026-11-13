"""Tournament projections owned by the existing recoverable account journal."""

import copy
import hashlib
import json
import uuid
from pathlib import Path

from .local_packs import PackStore
from .local_profile import validate_credits
from .tournament_reward_policy import VERSION, quote

_CACHE = {}


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def pack_source(receipt, kind, index):
    identity = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"tournament:{receipt['source_id']}:{kind}:{index}",
    )
    return {
        "reward_id": str(uuid.uuid5(identity, kind + "-pack")),
        "source_id": str(identity),
        "source_kind": kind,
        "account_id": receipt["account_id"],
        "persona_id": 1,
        "cycle_id": str(uuid.uuid5(
            uuid.NAMESPACE_URL, "tournament-run:" + receipt["run_id"],
        )),
        "policy_version": VERSION,
        "certification": "backend_only",
    }


def projections(profile, packs, receipt):
    calculation = quote(
        receipt["start"], receipt["result"],
        trophy_round=receipt["trophy_round"],
        shootout=receipt.get("shootout"),
    )
    if (profile.get("revival_total_xp") or 0) != receipt["start"]["start_total_xp"]:
        raise ValueError("Tournament XP changed after source creation")
    after_profile = copy.deepcopy(profile)
    coins = calculation["match"]["coins"] + calculation["championship"]["coins"]
    after_profile["credits"] = validate_credits(profile["credits"] + coins)
    after_profile["revival_total_xp"] = calculation["match"]["after"]["total_xp"]
    after_packs = copy.deepcopy(packs)
    grants = []
    deliveries = [("fixture", calculation["match"]["pack"]["definition"])]
    deliveries.extend(("season", name) for name in calculation["championship"]["packs"])
    for index, (kind, definition) in enumerate(deliveries):
        after_packs, grant = PackStore.source_grant_image(
            after_packs, definition, pack_source(receipt, kind, index),
        )
        grants.append(grant)
    if receipt.get("level_reward_start") is not None:
        # XP-004: level-ups earned by this tournament match, paid in the same images.
        from .level_rewards import grant_images, quote as level_quote
        match = calculation["match"]
        level = level_quote(receipt["level_reward_start"], match["start"]["level"], match["after"]["level"])
        calculation["level"] = level
        if level["levels"]:
            owner = str(uuid.uuid5(uuid.NAMESPACE_URL, "tournament-level:" + receipt["source_id"]))
            cycle = pack_source(receipt, "fixture", 0)["cycle_id"]
            raw_profile, raw_packs, record = grant_images(
                level, encoded(after_profile), encoded(after_packs), owner_id=owner,
                account_id=receipt["account_id"], persona_id=1, cycle_id=cycle, encode=encoded,
            )
            after_profile, after_packs = json.loads(raw_profile), json.loads(raw_packs)
            grants.extend(record["grants"])
    return after_profile, after_packs, calculation, grants


AWARDS_PROJECTION = "completion_and_result_bonus_v1"


def awards_reply(receipt):
    """FUT End coin fields for the original Awards screen (no wallet effect).

    01049e90 installs participationAward as MATCH COMPLETION and
    matchCoins - participationAward as the generic WIN BONUS. Completion is
    the same tier's LOSS payout at the snapshotted level, so the total and its
    rounding are unchanged and a loss shows no bonus.
    """
    from .difficulty_rewards import match_values
    from .native_match_reward_policy import response_fields

    total = receipt["calculation"]["match"]["coins"]
    if receipt.get("awards_projection") != AWARDS_PROJECTION:
        return response_fields(total)
    start = receipt["start"]
    completion = match_values(start["difficulty"], start["start_total_xp"], "L")["coins"]
    if not 0 <= completion <= total:
        raise ValueError("Completion exceeds tournament match total")
    return {"matchCoins": total, "participationAward": completion}


def prepare(account, source, result, shootout=None):
    account = Path(account)
    from .tournament_account import context as account_context

    account_id, _, _ = account_context(account)
    receipt = {
        "version": VERSION,
        "source_id": source["quote"]["source_id"],
        "end_sha256": source["end_sha256"],
        "tournament_id": source["quote"]["tournament_id"],
        "run_id": source["reward_run_id"],
        "account_id": account_id,
        "start": copy.deepcopy(source["reward_start"]),
        "result": result,
        "trophy_round": source["quote"]["round"] == 4,
        "report": copy.deepcopy(source["xp_report"]),
        # Presentation only (user 3 Nov): Awards shows completion + result
        # bonus. Older receipts lack this key and keep their exact replies.
        "awards_projection": AWARDS_PROJECTION,
    }
    if source.get("level_reward_start") is not None:
        receipt["level_reward_start"] = copy.deepcopy(source["level_reward_start"])
    if shootout is not None:
        receipt["shootout"] = shootout
    uuid.UUID(receipt["account_id"])
    before = {name: (account / name).read_bytes() for name in ("profile.json", "packs.json")}
    profile, packs, calculation, grants = projections(
        json.loads(before["profile.json"]), json.loads(before["packs.json"]), receipt,
    )
    PackStore(account / "packs.json")._validated(encoded(packs), 1)
    receipt.update(calculation=calculation, pack_grants=grants)
    return {
        "kind": VERSION,
        "receipt": receipt,
        "images": [
            {"name": name, "before": before[name].hex(), "after": encoded(value).hex()}
            for name, value in (("profile.json", profile), ("packs.json", packs))
        ],
    }


def _validate_bytes(raw):
    intent = json.loads(raw)
    if set(intent) != {"kind", "receipt", "images"} or intent["kind"] != VERSION:
        raise ValueError("Invalid tournament reward intent")
    images = intent["images"]
    if [image["name"] for image in images] != ["profile.json", "packs.json"]:
        raise ValueError("Tournament reward image targets differ")
    for image in images:
        if set(image) != {"name", "before", "after"}:
            raise ValueError("Invalid tournament reward image")
    receipt = intent["receipt"]
    if receipt.get("awards_projection", AWARDS_PROJECTION) != AWARDS_PROJECTION:
        raise ValueError("Unknown tournament awards projection")
    profile, packs, calculation, grants = projections(
        json.loads(bytes.fromhex(images[0]["before"])),
        json.loads(bytes.fromhex(images[1]["before"])), receipt,
    )
    if (
        receipt["calculation"] != calculation
        or receipt["pack_grants"] != grants
        or json.loads(bytes.fromhex(images[0]["after"])) != profile
        or json.loads(bytes.fromhex(images[1]["after"])) != packs
    ):
        raise ValueError("Tournament reward projections differ")
    return intent


def validate(intent):
    raw = encoded(intent)
    digest = hashlib.sha256(raw).digest()
    if digest not in _CACHE:
        value = _validate_bytes(raw)
        if len(_CACHE) >= 16:
            _CACHE.clear()
        _CACHE[digest] = value
    return copy.deepcopy(_CACHE[digest])
