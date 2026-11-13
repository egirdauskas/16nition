"""Serialize local HTTP account reads with recoverable multi-store commits."""
from functools import wraps
from threading import RLock
import os
import tempfile

ACCOUNT_LOCK = RLock()

def atomic(path, data):
    """Existing season journal's durable same-directory image replacement."""
    descriptor, name = tempfile.mkstemp(prefix=path.name+'.', suffix='.new', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(name): os.unlink(name)

def recover_images(account, images, *, writer=atomic, fault=None):
    """Apply an operation-validated intent, refusing all conflicts before writes.

    Callers validate target names, ownership and complete semantic deltas first.
    The journal remains prepared until every projection is durable.
    """
    projections = []
    for image in images:
        path = account/image['name']; actual = path.read_bytes()
        before = bytes.fromhex(image['before']); after = bytes.fromhex(image['after'])
        if actual not in (before, after):
            raise ValueError('Recovery conflict; unrelated change preserved')
        projections.append((path, actual, after))
    for index, (path, actual, after) in enumerate(projections):
        if actual != after: writer(path, after)
        if fault: fault('after_image', index)

def account_locked(function):
    @wraps(function)
    def locked(*args, **kwargs):
        with ACCOUNT_LOCK:
            return function(*args, **kwargs)
    return locked
