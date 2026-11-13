"""Supplied player nationality and encoded skill rating, never account copies."""

import copy
import hashlib

from .local_content_source import DB, META, cards
from scripts.local_football_db import FootballDB


_CACHE = {}


_DIGESTS = {}


def _digest():
    """Content hash of the supplied DB+metadata, memoized by file identity."""
    key = tuple((str(path), path.stat().st_ino, path.stat().st_mtime_ns, path.stat().st_size)
                for path in (DB, META))
    if key not in _DIGESTS:
        if len(_DIGESTS) >= 4:
            _DIGESTS.clear()
        _DIGESTS[key] = hashlib.sha256(DB.read_bytes() + META.read_bytes()).digest()
    return _DIGESTS[key]


def _table():
    cards()  # Reuse the preserved source admission/hash checks.
    digest = _digest()
    if digest not in _CACHE:
        database = FootballDB(DB, META)
        limit = database.table('players')['valid_count']
        value = {}
        for row in database.rows('players', ['playerid', 'nationality', 'skillmoves']):
            if row['row_index'] >= limit:
                continue
            if not 0 <= row['skillmoves'] <= 4:
                raise ValueError('Unmapped supplied skill rating')
            value[row['playerid']] = (row['nationality'], row['skillmoves'])
        if len(_CACHE) >= 2:
            _CACHE.clear()
        _CACHE[digest] = value
    return _CACHE[digest]


def facts():
    return copy.deepcopy(_table())


def player_facts(player_id, default=(0, 0)):
    """One player's immutable (nationality, skill code) without copying the table."""
    return _table().get(player_id, default)
