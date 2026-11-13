"""Lineups replaced by squad saves during the current client session.

Genuine run 1577 (fresh club, tournament 201 round 1): the stock client saved
a squad edit (slot 6 ...375 -> ...387) and then sent tournament PlaySim with
the pre-edit eleven plus manager. The backend had already committed the edit,
so the exact-current-lineup PlaySim check held the request and the Sim hung.

This module only remembers which lineups a squad save replaced in the same
client session, so a match validator can recognise such a pre-edit roster.
It never changes ownership, the saved squad, wallets or rewards.
"""
import json
from pathlib import Path

from .account_transaction import atomic
from .match_roster import MATCH_PLAYERS, STARTERS

NAME = 'squad-lineup-history.json'
VERSION = 'squad_lineup_history_v1'
LIMIT = 16
RAW_SID = b'x-fifa-local-original-sid'


def session_of(headers):
    raw = headers.get(RAW_SID, headers.get(b'x-ut-sid'))
    if raw is None:
        return None
    return raw.decode('ascii')


def snapshot(state):
    slots = sorted(state.active_lineup, key=lambda slot: slot.index)
    manager = state.active_manager.instance_id if state.active_manager else None
    return {
        'starters': [slot.instance_id for slot in slots if slot.index < STARTERS],
        'match_players': [slot.instance_id for slot in slots if slot.index < MATCH_PLAYERS],
        'manager': manager,
    }


def load(account):
    path = Path(account) / NAME
    if not path.exists():
        return {'version': VERSION, 'session': None, 'replaced': []}
    value = json.loads(path.read_bytes())
    if (type(value) is not dict or set(value) != {'version', 'session', 'replaced'}
            or value['version'] != VERSION or type(value['replaced']) is not list):
        raise ValueError('Unknown squad lineup history')
    return value


def record(account, headers, before, after):
    """Remember `before` when a committed squad save changed the match roster."""
    session = session_of(headers)
    if session is None or before == after or len(before['starters']) != STARTERS:
        return
    try:
        value = load(account)
    except (ValueError, OSError):
        # Never let this advisory history block an already committed squad save.
        value = {'version': VERSION, 'session': None, 'replaced': []}
    if value['session'] != session:
        value = {'version': VERSION, 'session': session, 'replaced': []}
    if before in value['replaced']:
        return
    value['replaced'] = (value['replaced'] + [before])[-LIMIT:]
    raw = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    atomic(Path(account) / NAME, raw)


def replaced_match(account, headers, ids, owned):
    """Return the replaced lineup whose starters (+manager) equal `ids`.

    Only lineups replaced in this same client session qualify, and every
    player must still be owned. Returns None when nothing matches.
    """
    session = session_of(headers)
    try:
        value = load(account)
    except (ValueError, OSError):
        return None
    if session is None or value['session'] != session:
        return None
    if len(ids) != len(set(ids)) or not set(ids) <= owned:
        return None
    for lineup in reversed(value['replaced']):
        expected = set(lineup['starters'])
        if lineup['manager'] is not None:
            expected.add(lineup['manager'])
        if set(ids) == expected and len(ids) == len(expected):
            return lineup
    return None
