"""Memoize pure derivations of server/policy/ by content hash.

AGENTS: validation that is a pure function of file bytes must be memoized by
content hash, returning deep copies and never caching failures. The key is the
SHA-256 of every file in server/policy/; a file is re-hashed only when its
(mtime_ns, size, inode) changes. Code constants and supplied static content are
fixed for the life of the process.

Measured (run 1524 lab profile): before this, every request rebuilt the pack
binding chain and Store catalogs (~1 s of ~1.7 s per request, serialized by
ACCOUNT_LOCK).
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
import hashlib
from pathlib import Path
import threading

POLICY_DIR = Path(__file__).parent / 'policy'
_LOCK = threading.RLock()
_FILE_HASHES = {}
_SCOPE = ContextVar('policy_memo_scope', default=None)


def request_scoped(function):
    """Compute the policy fingerprint once per request (the server never writes policy files)."""
    @wraps(function)
    def wrapper(*args, **kwargs):
        if _SCOPE.get() is not None:
            return function(*args, **kwargs)
        token = _SCOPE.set({})
        try:
            return function(*args, **kwargs)
        finally:
            _SCOPE.reset(token)
    return wrapper


def fingerprint():
    scope = _SCOPE.get()
    if scope is not None and 'fingerprint' in scope:
        return scope['fingerprint']
    value = _fingerprint()
    if scope is not None:
        scope['fingerprint'] = value
    return value


def _fingerprint():
    digest = hashlib.sha256()
    with _LOCK:
        for path in sorted(POLICY_DIR.iterdir()):
            if not path.is_file():
                continue
            stat = path.stat()
            key = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
            cached = _FILE_HASHES.get(path)
            if cached is None or cached[0] != key:
                cached = (key, hashlib.sha256(path.read_bytes()).digest())
                _FILE_HASHES[path] = cached
            digest.update(path.name.encode() + b'\0' + cached[1])
    return digest.digest()


def policy_memo(function):
    """Cache a zero-argument policy derivation; failures are not cached."""
    cache = {}

    @wraps(function)
    def wrapper():
        key = fingerprint()
        with _LOCK:
            if key in cache:
                return deepcopy(cache[key])
        value = function()
        with _LOCK:
            if len(cache) >= 4:
                cache.clear()
            cache[key] = deepcopy(value)
        return value

    wrapper.uncached = function
    return wrapper
