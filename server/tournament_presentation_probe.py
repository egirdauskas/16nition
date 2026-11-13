"""Isolated read-only award-record probe; it grants no reward or ownership."""

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NAME = 'tournament-presentation-probe.json'
_CACHE = {}


def award(account):
    account = Path(account).resolve()
    path = account / NAME
    if not path.exists():
        return None
    if ROOT / 'reports' not in account.parents or account.name != 'isolated-account':
        raise ValueError('Uncertified award presentation requires archived isolation')
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).digest()
    if digest not in _CACHE:
        value = json.loads(raw)
        if (
            type(value) is not dict
            or set(value) != {'version', 'cup_id', 'award_type', 'definition'}
            or value['version'] != 'isolated_tournament_bonus_probe_v1'
            or type(value['cup_id']) is not int
            or value['cup_id'] != 201
            or type(value['award_type']) is not int
            or value['award_type'] not in (2, 3)
            or value['definition'] != 'revival_premium_gold_mixed_specials_v8'
        ):
            raise ValueError('Unsupported tournament presentation probe')
        if len(_CACHE) >= 4:
            _CACHE.clear()
        _CACHE[digest] = value
    value = copy.deepcopy(_CACHE[digest])
    from . import native_pack_sessions as sessions

    if sessions.ACCOUNT != account:
        raise ValueError('Probe requires the existing native typed caption bank')
    names = sessions.definitions()
    key = sessions.FIRST + names.index(value['definition']) * sessions.SLOTS
    return value['cup_id'], {'awardType': value['award_type'], 'value': 1, 'halid': key}
