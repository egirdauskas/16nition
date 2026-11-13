"""Carry the genuine pre-club login across atomic CreateUser publication.

Opt-in for Ignition only. The original client receives its eventual standard
pack-session code/SID during setup. Its actual auth request is persisted before
the reply; after creation it commits through the existing session coordinator.
There is no fabricated callback, HTTP replay or financial grant here.
"""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from .account_transaction import atomic

ACCOUNT = None
VERSION = 'ignition_setup_auth_v1'


def path_for(account):
    account = Path(account)
    return account.with_name('.' + account.name + '.bootstrap-auth.json')


def configure(account=None):
    global ACCOUNT
    ACCOUNT = Path(account).resolve() if account is not None else None


def code():
    if ACCOUNT is None:
        return None
    from .first_run_account import pending_session
    if pending_session(ACCOUNT) is None:
        return None
    from .native_pack_sessions import code as session_code
    return session_code(1, account=ACCOUNT)


def sid(token):
    expected = code()
    if expected is None or token != expected:
        return None
    from .native_pack_sessions import sid as session_sid
    return session_sid(token)


@lru_cache(maxsize=32)
def _decode(raw):
    value = json.loads(raw)
    if (set(value) != {'version', 'account', 'creation_id', 'headers', 'body'}
            or value['version'] != VERSION or type(value['headers']) is not list):
        raise ValueError('Invalid setup login receipt')
    headers = {bytes.fromhex(k): bytes.fromhex(v) for k, v in value['headers']}
    body = bytes.fromhex(value['body'])
    if len(headers) != len(value['headers']) or len(body) != 1000:
        raise ValueError('Invalid setup login request')
    return value


def record(method, target, headers, body):
    if ACCOUNT is None or method != 'POST' or target != '/ut/auth':
        return
    expected = code()
    if expected is None:
        return
    from .game_auth import response_for
    from .first_run_account import pending_session
    if response_for(method, target, headers, body) is None:
        raise ValueError('Invalid pending club login')
    payload = json.loads(body.rstrip(b'\0'))
    if payload['identification']['authCode'] != expected:
        raise ValueError('Pending club login code conflict')
    value = {
        'version': VERSION, 'account': str(ACCOUNT),
        'creation_id': pending_session(ACCOUNT)['creation_id'],
        'headers': [[k.hex(), v.hex()] for k, v in sorted(headers.items())],
        'body': body.hex(),
    }
    path = path_for(ACCOUNT)
    if path.exists():
        previous = deepcopy(_decode(path.read_bytes()))
        if any(previous[key] != value[key] for key in ('account', 'creation_id', 'body')):
            raise ValueError('Conflicting pending club login; receipt preserved')
        return
    atomic(path, (json.dumps(value, indent=2, sort_keys=True) + '\n').encode())


def promote(account):
    if ACCOUNT is None or Path(account).resolve() != ACCOUNT:
        return
    path = path_for(ACCOUNT)
    if not path.exists():
        raise ValueError('Completed setup lacks its genuine login receipt')
    value = deepcopy(_decode(path.read_bytes()))
    from .first_run_account import inspect
    owner = inspect(ACCOUNT)
    if value['account'] != str(ACCOUNT) or value['creation_id'] != owner['creation_id']:
        raise ValueError('Setup login owner conflict')
    from .native_pack_sessions import commit_auth
    headers = {bytes.fromhex(k): bytes.fromhex(v) for k, v in value['headers']}
    commit_auth('POST', '/ut/auth', headers, bytes.fromhex(value['body']))
    configure()
