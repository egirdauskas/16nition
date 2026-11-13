"""Explicit Android catalog compiled by the unchanged historical review path.

The host keeps reviewing original research. Android consumes the exact reviewed
result, bound to the bundled policies, without shipping research photographs.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

_CATALOG = None
_DECODED = {}


def _decode(raw):
    from .reconstructed_specials import SpecialVersion
    value = json.loads(raw)
    if (value.get('version') != 1
            or value.get('classification') != 'compiled_reviewed_reconstruction'):
        raise ValueError('Unknown compiled special catalog')
    index = value['index']
    versions = {}
    for key, row in index['versions'].items():
        if key != row['record_id']:
            raise ValueError('Compiled special identity differs')
        row = dict(row)
        row['attributes'] = tuple(row['attributes'])
        versions[key] = SpecialVersion(**row)
    index['versions'] = versions
    for field in ('canonical_ids', 'pool_ids'):
        index[field] = tuple(index[field])
        if not set(index[field]) <= versions.keys():
            raise ValueError('Compiled special pool contains an unknown version')
    if not set(index['aliases'].values()) <= versions.keys():
        raise ValueError('Compiled special alias differs')
    return value


def configure(root, raw=None):
    global _CATALOG
    if raw is None:
        _CATALOG = None
    else:
        key = hashlib.sha256(raw).digest()
        if key not in _DECODED:
            decoded = _decode(raw)
            if len(_DECODED) >= 4:
                _DECODED.clear()
            _DECODED[key] = decoded
        value = deepcopy(_DECODED[key])
        for name, digest in value['policy_sha256'].items():
            if hashlib.sha256((Path(root) / name).read_bytes()).hexdigest() != digest:
                raise ValueError('Compiled special policy differs: ' + name)
        _CATALOG = value['index']
    from .reconstructed_specials import review_index
    review_index.cache_clear()


def index():
    return deepcopy(_CATALOG)
