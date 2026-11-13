"""Prospective tournament reward quotes; no wire replies or account writes."""

import copy
import hashlib
import json
from pathlib import Path

from .account_progression import level_state
from .difficulty_rewards import match_values
from .pack_policy import load_definitions


PATH = Path(__file__).parent / "policy/tournament-rewards-v2.json"
VERSION = "tournament_rewards_v2"
_CACHE = {}


def load_policy(path=PATH):
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest in _CACHE:
        return copy.deepcopy(_CACHE[digest])
    value = json.loads(raw)
    if (
        value.get("version") != VERSION
        or value.get("classification") != "revival_policy"
        or value.get("ownership") != "untradeable"
        or value.get("retroactive") is not False
        or value.get("default_enabled") is not False
        or value.get("stock_delivery_enabled") is not False
        or value.get("difficulty_policy") != "difficulty_rewards_v1"
        or value.get("match_pack_divisions") != {
            "0": 10, "1": 8, "2": 7, "3": 5, "4": 3, "5": 2, "6": 1,
        }
    ):
        raise ValueError("Invalid tournament reward policy")
    prizes = value.get("championship")
    if type(prizes) is not dict or set(prizes) != {str(i) for i in range(201, 206)}:
        raise ValueError("Five explicit cup prizes required")
    definitions = load_definitions()
    for prize in prizes.values():
        if (
            type(prize) is not dict
            or set(prize) != {"coins", "first_win_packs"}
            or type(prize["coins"]) is not int
            or not 0 < prize["coins"] <= 10**6
            or type(prize["first_win_packs"]) is not list
            or not prize["first_win_packs"]
            or len(prize["first_win_packs"]) != len(set(prize["first_win_packs"]))
            or any(name not in definitions for name in prize["first_win_packs"])
        ):
            raise ValueError("Unsupported tournament championship prize")
    if len(_CACHE) >= 8:
        _CACHE.clear()
    _CACHE[digest] = value
    return copy.deepcopy(value)


def snapshot(tournament_id, difficulty, start_total_xp, prior_trophies, path=PATH):
    policy = load_policy(path)
    if type(tournament_id) is not int or str(tournament_id) not in policy["championship"]:
        raise ValueError("Unknown tournament reward source")
    if type(difficulty) is not int or str(difficulty) not in policy["match_pack_divisions"]:
        raise ValueError("Unknown tournament difficulty")
    if type(prior_trophies) is not int or prior_trophies < 0:
        raise ValueError("Invalid trophy history")
    from .difficulty_rewards import POLICY as difficulty_policy
    from .reward_store_parity import PATH as pack_policy
    from .reward_store_parity import snapshot as pack_snapshot

    division = policy["match_pack_divisions"][str(difficulty)]
    match_packs = pack_snapshot(division, current=False)["outcomes"]
    names = {row["definition"] for row in match_packs.values()}
    names.update(policy["championship"][str(tournament_id)]["first_win_packs"])
    definitions = load_definitions()
    return {
        "version": VERSION,
        "policy_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "tournament_id": tournament_id,
        "difficulty": difficulty,
        "start_total_xp": level_state(start_total_xp)["total_xp"],
        "prior_trophies": prior_trophies,
        "difficulty_policy_sha256": hashlib.sha256(difficulty_policy.read_bytes()).hexdigest(),
        "pack_policy_sha256": hashlib.sha256(pack_policy.read_bytes()).hexdigest(),
        "definition_sha256": {
            name: hashlib.sha256((json.dumps(definitions[name], indent=2, sort_keys=True) + "\n").encode()).hexdigest()
            for name in sorted(names)
        },
    }


def quote(start, result, *, trophy_round=False, shootout=None):
    if type(start) is not dict or start != snapshot(
        start.get("tournament_id"), start.get("difficulty"),
        start.get("start_total_xp"), start.get("prior_trophies"),
    ):
        raise ValueError("Tournament reward snapshot differs")
    if type(trophy_round) is not bool:
        raise ValueError("Explicit trophy-round classification required")
    policy = load_policy()
    match = match_values(start["difficulty"], start["start_total_xp"], result)
    from .reward_store_parity import snapshot as pack_snapshot

    division = policy["match_pack_divisions"][str(start["difficulty"])]
    pack = pack_snapshot(division, current=False)["outcomes"][result]
    title = policy["championship"][str(start["tournament_id"])]
    # 1391: a knockout level after extra time is a match DRAW whose tie is
    # decided by penalties (End endReason). The shoot-out winner advances.
    if shootout not in (None, "W", "L") or (shootout is not None and result != "D"):
        raise ValueError("Shoot-out outcome requires a drawn match")
    won = trophy_round and (result == "W" or shootout == "W")
    return {
        "version": VERSION,
        "match": {**match, "pack": pack},
        "championship": {
            "coins": title["coins"] if won else 0,
            "packs": copy.deepcopy(title["first_win_packs"])
            if won and start["prior_trophies"] == 0 else [],
            "first_win": won and start["prior_trophies"] == 0,
        },
    }


def allowed_pack_definitions():
    from .reward_store_parity import policy as store_policy

    policy = load_policy()
    names = {
        row["definition"] for row in store_policy()["bindings"].values()
    }
    for prize in policy["championship"].values():
        names.update(prize["first_win_packs"])
    return names
