"""Sealed draw history: past receipts verified by digest instead of re-drawn.

Pack openings and player exchanges are validated by re-drawing them from the
live special pool. Admitting new specials changes that pool, so history drawn
from an older pool can no longer be re-derived. A seal records, once and with a
backup taken first, the exact canonical bytes (SHA-256) of every existing
receipt. Sealed receipts must match their digest exactly; everything opened
after the seal is still re-drawn and verified from the current pool.

User authorization, 7 November 2026: "don't want this to be treated like a
regular thing but it may be relevant for later patches". Each seal is an
explicit, versioned migration step (scripts/seal_draw_history.py), never
automatic. A later patch appends a new seal generation; old generations stay.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

FILE = 'draw-history-seal.json'
VERSION = 'draw_history_seal_v1'
KINDS = ('packs', 'player_exchanges')
_CACHE = {}


def digest(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def _validated(raw, account):
    value = json.loads(raw)
    if type(value) is not dict or set(value) != {'version', 'account', 'generations'} or value['version'] != VERSION:
        raise ValueError('Invalid draw-history seal')
    if value['account'] != str(account):
        raise ValueError('Draw-history seal belongs to another account')
    merged = {kind: {} for kind in KINDS}
    for generation in value['generations']:
        if (type(generation) is not dict
                or set(generation) != {'sealed_at', 'reason', 'special_pool_sha256', 'backup', 'records'}
                or set(generation['records']) != set(KINDS)):
            raise ValueError('Invalid draw-history seal generation')
        for kind in KINDS:
            for key, sha in generation['records'][kind].items():
                if type(sha) is not str or len(sha) != 64:
                    raise ValueError('Invalid sealed digest')
                if merged[kind].get(key, sha) != sha:
                    raise ValueError('Sealed record changed between generations')
                merged[kind][key] = sha
    return merged


def records(account):
    """{kind: {key: sha}} for the account, or empty when nothing is sealed."""
    account = Path(account).resolve()
    path = account / FILE
    if not path.exists():
        return {kind: {} for kind in KINDS}
    if path.is_symlink():
        raise ValueError('Draw-history seal must be a regular file')
    raw = path.read_bytes()
    key = (str(account), hashlib.sha256(raw).digest())
    if key not in _CACHE:
        if len(_CACHE) >= 8:
            _CACHE.clear()
        _CACHE[key] = _validated(raw, account)
    return deepcopy(_CACHE[key])


def fingerprint(account):
    path = Path(account) / FILE
    return hashlib.sha256(path.read_bytes()).digest() if path.exists() else b''


def is_sealed(account, kind, key, record):
    """True when the record is sealed and matches; raises if sealed but changed."""
    sealed = records(account)[kind].get(str(key))
    if sealed is None:
        return False
    if digest(record) != sealed:
        raise ValueError('Sealed %s record %s changed' % (kind, key))
    return True


def exchange_key(receipt):
    # exchange_id, not session_hash: two exchanges in one session share a session hash
    # (normal account, 7 Nov 2026). Generation 1 of that account was keyed by session hash;
    # those entries are kept (append-only) but no longer consulted.
    return receipt['exchange_id']


def special_pool_sha256():
    from .reconstructed_specials import review_index
    return hashlib.sha256(json.dumps(sorted(review_index()['pool_ids'])).encode()).hexdigest()


def seal(account, reason, backup, sealed_at):
    """Add a seal generation for every current pack and exchange receipt."""
    account = Path(account).resolve()
    packs = json.loads((account / 'packs.json').read_bytes())
    if packs.get('prepared'):
        raise ValueError('Recover the pending pack opening before sealing')
    pack_records = {str(r['catalog_id']): digest(r) for r in packs['consumed']}
    exchange_records = {}
    path = account / 'player-exchanges.json'
    if path.exists():
        exchanges = json.loads(path.read_bytes())
        if exchanges.get('prepared') or exchanges.get('active'):
            raise ValueError('Finish the pending player exchange before sealing')
        exchange_records = {exchange_key(r): digest(r) for r in exchanges['receipts']}
    target = account / FILE
    value = (json.loads(target.read_bytes()) if target.exists()
             else {'version': VERSION, 'account': str(account), 'generations': []})
    value['generations'].append({'sealed_at': sealed_at, 'reason': reason, 'special_pool_sha256': special_pool_sha256(),
                                 'backup': str(backup),
                                 'records': {'packs': pack_records, 'player_exchanges': exchange_records}})
    encoded = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    _validated(encoded, account)
    from .account_transaction import atomic
    atomic(target, encoded)
    return value


def seal_copy(account, source, reason='lab copy of a pre-migration archive'):
    """Seal a disposable copy of an account archived before a pool change (idempotent).

    A copy made from an archive holds receipts drawn from the pool of its time; like the live
    account at the migration it must be sealed before it can load. Archives stay untouched.
    """
    account = Path(account).resolve()
    path = account / FILE
    if path.exists():
        value = json.loads(path.read_bytes())
        if value.get('account') != str(account):
            # Copied together with its account: rebind to the copy, as account import does.
            value['account'] = str(account)
            encoded = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
            _validated(encoded, account)
            from .account_transaction import atomic
            atomic(path, encoded)
        sealed = records(account)
        packs = json.loads((account / 'packs.json').read_bytes())
        if all(str(r['catalog_id']) in sealed['packs'] for r in packs['consumed']):
            return sealed
    from datetime import datetime, timezone
    seal(account, reason, Path(source).resolve(), datetime.now(timezone.utc).isoformat())
    return records(account)
