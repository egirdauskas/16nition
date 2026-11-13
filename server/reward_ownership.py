"""Read persisted ownership flags; cache only an immutable file identity.

Atomic replacement changes inode/mtime. No separate registry or reward ledger
becomes authoritative; FootballStore remains the owner and validates writes.
"""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=8)
def _ids(path, inode, mtime, size, ctime):
    value=json.loads(Path(path).read_bytes()).get('untradeable_instance_ids',[])
    if type(value) is not list or len(set(value))!=len(value) or any(type(i) is not int or i<=0 for i in value):
        raise ValueError('Invalid reward ownership flags')
    return frozenset(value)


def untradeable(account, instance_id):
    if account is None:return False
    path=Path(account).resolve()/'football.json'
    if not path.exists():return False
    s=path.stat()
    return instance_id in _ids(str(path),s.st_ino,s.st_mtime_ns,s.st_size,s.st_ctime_ns)
