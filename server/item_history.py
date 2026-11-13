"""CLUB-005 item history for PLAYER BIO > Item Details (user design 5 Nov 2026).

Stock mapping (isolated probes 1446/1447): the item JSON key ``timestamp`` is
Date Issued, ``owners`` Number of Owners, ``lastSalePrice`` Bought For, and
``statsList`` index 0..3 Matches Played / Goals Scored / Yellow / Red Cards.

Design (explicit revival_policy):
- Date Issued: the real time (stored in UTC; sent as the local calendar date)
  a card is first seen in the club after the
  feature was switched on (instance IDs at or above the recorded baseline).
  Market purchases use their recorded settlement time. Older cards stay 0,
  which the stock client shows as 01/01/1970 (user: leave unknown dates blank).
- Number of Owners: 1, plus 1 for a card bought on the Market.
- Bought For: the Market price paid; otherwise 0 (the existing default).
- Matches Played / Goals Scored: counted per card from matches committed after
  the feature was switched on (``record_match``); cards stay 0.

State lives in ``item-history.json``; its presence selects the feature.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

from .account_transaction import account_locked, atomic

NAME = 'item-history.json'
VERSION = 'item_history_v1'
_CACHE = {}


def path(account):
    return Path(account) / NAME


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def _validated(raw):
    value = json.loads(raw)
    if (type(value) is not dict
            or set(value) != {'version', 'baseline_next_instance_id', 'enabled_at', 'issued', 'stats',
                              'counted', 'pending_goals', 'seasons_baseline'}
            or value['version'] != VERSION
            or type(value['baseline_next_instance_id']) is not int
            or type(value['enabled_at']) is not int or type(value['seasons_baseline']) is not int
            or type(value['issued']) is not dict or type(value['stats']) is not dict
            or type(value['counted']) is not list or type(value['pending_goals']) is not list):
        raise ValueError('Invalid item history')
    for key, stamp in value['issued'].items():
        if not key.isdigit() or int(key) < value['baseline_next_instance_id'] or type(stamp) is not int:
            raise ValueError('Invalid item issue record')
    for key, row in value['stats'].items():
        if (not key.isdigit() or type(row) is not dict or set(row) != {'matches', 'goals'}
                or any(type(v) is not int or v < 0 for v in row.values())):
            raise ValueError('Invalid item statistics')
    if len(set(value['counted'])) != len(value['counted']):
        raise ValueError('Match counted twice in item history')
    return value


def _cached(file, loader):
    """Memoize a pure parse of file bytes by (path, mtime, size) then content hash."""
    try:
        stat = file.stat()
    except FileNotFoundError:
        return None
    key = (str(file), stat.st_ino, stat.st_mtime_ns, stat.st_size)
    hit = _CACHE.get(key)
    if hit is None:
        raw = file.read_bytes()
        hit = loader(raw)
        if len(_CACHE) >= 32:
            _CACHE.clear()
        _CACHE[key] = hit
    return hit


def load(account):
    value = _cached(path(account), _validated)
    return deepcopy(value) if value is not None else None


def enabled(account):
    return account is not None and path(account).is_file()


def _market_index(raw):
    index = {}
    for listing in json.loads(raw)['listings']:
        receipt = listing.get('settlement')
        if receipt and receipt.get('buyer') == 'player' and receipt.get('instance_id') is not None:
            index[receipt['instance_id']] = {'at': receipt['at'], 'price': receipt['price']}
    return index


def market_index(account):
    return _cached(Path(account) / 'market.json', _market_index) or {}


def enable(account, now=None):
    """Create the history file; only cards from now on get a date."""
    account = Path(account)
    if path(account).exists():
        raise FileExistsError('Item history already enabled')
    football = json.loads((account / 'football.json').read_bytes())
    seasons = account / 'native-seasons.json'
    played = len(json.loads(seasons.read_bytes())['matches']) if seasons.exists() else 0
    value = {'version': VERSION, 'baseline_next_instance_id': football['next_instance_id'],
             'seasons_baseline': played,
             'enabled_at': int(now if now is not None else time.time()),
             'issued': {}, 'stats': {}, 'counted': [], 'pending_goals': []}
    atomic(path(account), encode(value))
    return value


@account_locked
def stamp_new(account, now=None):
    """Record the issue time of every newly owned card (idempotent)."""
    value = load(account)
    if value is None:
        return
    football = json.loads((Path(account) / 'football.json').read_bytes())
    ids = {row['instance_id'] for name in ('owned_items', 'owned_consumables', 'owned_club_items')
           for row in football.get(name, [])}
    stamp = int(now if now is not None else time.time())
    new = [i for i in ids if i >= value['baseline_next_instance_id'] and str(i) not in value['issued']]
    if not new:
        return
    for instance in new:
        value['issued'][str(instance)] = stamp
    atomic(path(account), encode(value))


def displayed(stamp):
    """Wire value whose UTC date equals the local calendar date of ``stamp``.

    The stock client formats Date Issued with gmtime (00b5ce90 -> 00172d04), so a
    true UTC time would show yesterday's date for cards obtained just after
    local midnight. Shift by this machine's UTC offset at that moment (DST
    aware). 0 stays 0 (unknown, shown as 01/01/1970).
    """
    if not stamp:
        return 0
    return stamp + time.localtime(stamp).tm_gmtoff


def fields(account, instance_id):
    """Item JSON keys for one card; empty when the feature is off."""
    if not enabled(account):
        return {}
    value = load(account)
    if instance_id >= value['baseline_next_instance_id'] and str(instance_id) not in value['issued']:
        stamp_new(account)
        value = load(account)
    bought = market_index(account).get(instance_id)
    issued = bought['at'] if bought else value['issued'].get(str(instance_id), 0)
    issued = displayed(issued)
    stats = value['stats'].get(str(instance_id), {'matches': 0, 'goals': 0})
    result = {'timestamp': issued, 'owners': 2 if bought else 1,
              'statsList': [{'index': 0, 'value': stats['matches']}, {'index': 1, 'value': stats['goals']},
                            {'index': 2, 'value': 0}, {'index': 3, 'value': 0}]}
    if bought:
        result['lastSalePrice'] = bought['price']
    return result


@account_locked
def record_goal(account, body, values):
    """Keep one stock ScoreAGoal event until its match is committed (retries dedupe)."""
    if not enabled(account) or 'MatchId' not in values or 'PlayerId' not in values:
        return
    value = load(account)
    digest = hashlib.sha256(body).hexdigest()
    if any(g['sha256'] == digest for g in value['pending_goals']):
        return
    value['pending_goals'].append({'sha256': digest, 'match_id': str(values['MatchId']),
                                   'player_id': int(values['PlayerId'])})
    atomic(path(account), encode(value))


@account_locked
def record_match(account, source_id, match_id, end_body):
    """Count one committed match once: starters +1 match, scorers +1 goal each.

    ``end_body`` is the stock End JSON; its ``items`` list the squad with the
    eleven starters first. Goals are the pending ScoreAGoal events carrying this
    match's session id, credited to the squad card of that base player.
    """
    if not enabled(account):
        return False
    value = load(account)
    if source_id in value['counted']:
        return False
    items = [row['id'] for row in json.loads(end_body)['items']]
    football = json.loads((Path(account) / 'football.json').read_bytes())
    owned = {row['instance_id']: row['resource_id'] for row in football.get('owned_items', [])}
    squad = [i for i in items if i in owned]

    def row(instance):
        return value['stats'].setdefault(str(instance), {'matches': 0, 'goals': 0})
    for instance in squad[:11]:
        row(instance)['matches'] += 1
    mine = [g for g in value['pending_goals'] if g['match_id'] == str(match_id)]
    for goal in mine:
        scorer = next((i for i in squad if owned[i] & 0xffffff == goal['player_id']), None)
        if scorer is not None:
            row(scorer)['goals'] += 1
    # Consume this match's goals; keep a bounded tail of other sessions' events.
    value['pending_goals'] = [g for g in value['pending_goals'] if g['match_id'] != str(match_id)][-100:]
    value['counted'].append(source_id)
    atomic(path(account), encode(value))
    return True


def reconcile_seasons(account):
    """Count Seasons matches committed since enabling (crash-safe, idempotent)."""
    if not enabled(account):
        return
    from .native_match_session import session_id
    value = load(account)
    state = json.loads((Path(account) / 'native-seasons.json').read_bytes())
    for match in state['matches'][value['seasons_baseline']:]:
        if (match.get('status') == 'committed' and match.get('end_body_hex')
                and not match.get('native_match_forfeit') and match['id'] not in value['counted']):
            record_match(account, match['id'], session_id(match['id']), bytes.fromhex(match['end_body_hex']))


def validate_file(account):
    """Read-only backup check."""
    if path(account).exists():
        _validated(path(account).read_bytes())
