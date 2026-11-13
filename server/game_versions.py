"""Supported original FIFA 16 builds, identified by EA signer + versionCode.

An original is accepted by identity (package, EA signing certificate and a
listed versionCode), not by a whole-file hash. Each version still carries
exact per-member hashes inside the game patch bundle, because a binary delta
can only be applied to the exact bytes it was built from.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

POLICY = Path(__file__).resolve().parent / 'data/ignition-game-versions-v1.json'
SCHEMA = 'ignition-game-versions/1'
EXPANSION_NAME = re.compile(r'^(main|patch)\.(\d+)\.com\.ea\.gp\.fifaworld\.obb$')
HEX64 = re.compile(r'^[0-9a-f]{64}$')
_CACHE = {}


def _validate(value):
    if value.get('schema') != SCHEMA or value.get('package') != 'com.ea.gp.fifaworld':
        raise ValueError('Unknown game version policy')
    if not HEX64.match(value.get('signer_sha256', '')):
        raise ValueError('Invalid signer digest')
    versions = value.get('versions')
    if not isinstance(versions, dict) or not versions:
        raise ValueError('No supported game versions')
    outputs = set()
    hashes = {}
    for code, entry in versions.items():
        if not code.isdigit() or entry['output_version_code'] <= int(code):
            raise ValueError('Invalid game version mapping')
        if entry['output_version_code'] in outputs:
            raise ValueError('Duplicate prepared versionCode')
        outputs.add(entry['output_version_code'])
        if entry.get('store_caption_style', 'stacked') not in ('stacked', 'single_line'):
            raise ValueError('Unknown store caption style')
        if entry.get('identity_refresh_grant', 'hold') not in ('hold', 'answer'):
            raise ValueError('Unknown identity refresh grant mode')
        mains = [name for name in entry['expansions'] if name.startswith('main.')]
        if len(mains) != 1 or len(entry['expansions']) > 2:
            raise ValueError('Each version needs one main and at most one patch expansion')
        for name, digest in entry['expansions'].items():
            if not EXPANSION_NAME.match(name) or not HEX64.match(digest):
                raise ValueError('Invalid expansion definition')
            if hashes.setdefault(name, digest) != digest:
                raise ValueError('One expansion name cannot have two hashes')
    return value


def policy(raw=None):
    """Validated policy, memoized by content hash; failures are never cached."""
    if raw is None:
        raw = POLICY.read_bytes()
    key = hashlib.sha256(raw).digest()
    if key not in _CACHE:
        value = _validate(json.loads(raw))
        if len(_CACHE) >= 4:
            _CACHE.clear()
        _CACHE[key] = value
    return deepcopy(_CACHE[key])


def version(code, raw=None):
    entry = policy(raw)['versions'].get(str(int(code)))
    if entry is None:
        raise ValueError('Unsupported FIFA 16 version ' + str(code))
    return entry


def expansion_hashes(raw=None):
    """Every supported expansion name mapped to its single expected SHA256."""
    result = {}
    for entry in policy(raw)['versions'].values():
        result.update(entry['expansions'])
    return result


def output_version_name(code, raw=None):
    value = policy(raw)
    return '{}-ignition.{}'.format(version(code, raw)['version_name'], value['ignition_revision'])
