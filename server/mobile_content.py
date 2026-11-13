"""Prepare the backend's two original resources from locally selected OBBs.

Read-only BIG4 input, bounded decoding and atomic publication. Account stores
and game expansion files are never modified by preparation.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import struct

LIMIT = 64 * 1024 * 1024
_MANIFESTS = {}


def open_source(source):
    if type(source) is int:
        # A SAF grant supplies an FD, not permission to reopen its backing path.
        stream = os.fdopen(os.dup(source), 'rb')
    else:
        stream = open(source, 'rb')
    try:
        stream.seek(0)
    except OSError:
        stream.close()
        raise ValueError('Choose OBB files from local device storage') from None
    return stream


def sha_file(path):
    digest = hashlib.sha256()
    with open_source(path) as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _manifest(raw):
    value = json.loads(raw)
    if value.get('version') != 2 or value.get('classification') != 'local_obb_preparation':
        raise ValueError('Unknown expansion preparation manifest')
    if len(value['files']) != 2 or len(value['expansions']) != 2:
        raise ValueError('Unexpected expansion resource set')
    for name, definition in value['files'].items():
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or '\\' in name
                or not name.startswith('native/content/')
                or definition['expansion'] not in value['expansions']
                or not 0 < definition['size'] <= LIMIT):
            raise ValueError('Unsafe expansion resource definition')
    return value


def manifest(raw):
    # Successful byte validations are cached, failures are never cached.
    key = hashlib.sha256(raw).digest()
    if key not in _MANIFESTS:
        value = _manifest(raw)
        if len(_MANIFESTS) >= 8:
            _MANIFESTS.clear()
        _MANIFESTS[key] = value
    return deepcopy(_MANIFESTS[key])


def big_index(source):
    source.seek(0, os.SEEK_END)
    length = source.tell()
    source.seek(0)
    header = source.read(16)
    if len(header) != 16 or header[:4] not in (b'BIG4', b'BIGF'):
        raise ValueError('Not an original BIG archive')
    count, size = struct.unpack('>II', header[8:])
    if not 0 < count <= 100000 or not 16 <= size <= min(length, 16 * 1024 * 1024):
        raise ValueError('Invalid BIG index bounds')
    data = source.read(size - 16)
    position = 0
    result = {}
    for _ in range(count):
        if position + 8 > len(data):
            raise ValueError('Truncated BIG index')
        offset, stored_size = struct.unpack_from('>II', data, position)
        position += 8
        end = data.find(b'\0', position)
        if end < 0:
            raise ValueError('Unterminated BIG entry')
        name = data[position:end].decode('utf-8').replace('\\', '/')
        position = end + 1
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or name in result
                or not name or offset < size or offset + stored_size > length):
            raise ValueError('Invalid BIG entry bounds or path')
        result[name] = (offset, stored_size)
    return result


def refpack(data, expected_size):
    """Bounded version of the lab's supplied single-chunk RefPack decoder."""
    if not 0 < expected_size <= LIMIT:
        raise ValueError('Invalid expanded resource size')
    if not data.startswith(b'chunkref'):
        if len(data) != expected_size:
            raise ValueError('Expanded resource size differs')
        return data
    if (len(data) < 54 or int.from_bytes(data[20:24], 'big') != 1
            or data[48:50] != b'\x10\xfb'
            or int.from_bytes(data[50:53], 'big') != expected_size):
        raise ValueError('Unsupported RefPack header')
    position = 53
    output = bytearray()

    def take(count):
        nonlocal position
        end = position + count
        if end > len(data):
            raise ValueError('Truncated RefPack stream')
        value = data[position:end]
        position = end
        return value

    while True:
        control = take(1)[0]
        length = 0
        offset = 0
        if control >= 0xfc:
            literal = control & 3
        elif control >= 0xe0:
            literal = ((control & 31) << 2) + 4
        elif control >= 0xc0:
            b, d, e = take(3)
            literal = control & 3
            length = ((control & 12) << 6) + e + 5
            offset = ((control & 16) << 12) + (b << 8) + d + 1
        elif control >= 0x80:
            b, d = take(2)
            literal = b >> 6
            length = (control & 63) + 4
            offset = ((b & 63) << 8) + d + 1
        else:
            b = take(1)[0]
            literal = control & 3
            length = ((control >> 2) & 7) + 3
            offset = ((control & 96) << 3) + b + 1
        if len(output) + literal + length > expected_size:
            raise ValueError('RefPack output exceeds expected size')
        output.extend(take(literal))
        if length and not 0 < offset <= len(output):
            raise ValueError('Invalid RefPack back reference')
        for _ in range(length):
            output.append(output[-offset])
        if control >= 0xfc:
            break
    if len(output) != expected_size:
        raise ValueError('Expanded resource size differs')
    return bytes(output)


def destination(private, raw):
    return Path(private) / 'prepared-content' / hashlib.sha256(raw).hexdigest()


def ready(private, raw):
    value = manifest(raw)
    root = destination(private, raw)
    marker = root / 'complete.json'
    if not marker.is_file():
        return False
    expected = {name: definition['sha256'] for name, definition in value['files'].items()}
    if json.loads(marker.read_bytes()) != expected:
        raise ValueError('Prepared expansion receipt differs')
    for name, definition in value['files'].items():
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != definition['size']:
            raise ValueError('Prepared expansion resource is missing or changed')
    return True


def prepare(private, raw, sources):
    """Sources are local paths or borrowed seekable Android SAF descriptors."""
    value = manifest(raw)
    if ready(private, raw):
        return str(destination(private, raw))
    # Only expansions that resources are extracted from are required; the
    # selected game version's other expansion (its patch) is not read here.
    required = {definition['expansion'] for definition in value['files'].values()}
    if not required <= set(sources):
        raise ValueError('Select the original main OBB file in Setup')
    # Hash streams once during preparation, never load a whole expansion in RAM.
    for name in sorted(required):
        if sha_file(sources[name]) != value['expansions'][name]:
            raise ValueError('Expansion hash differs: ' + name)
    root = destination(private, raw)
    stage = root.with_name(root.name + '.preparing')
    root.parent.mkdir(parents=True, exist_ok=True)
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    try:
        for expansion in sorted(required):
            resources = [(name, entry) for name, entry in value['files'].items()
                         if entry['expansion'] == expansion]
            if not resources:
                continue
            with open_source(sources[expansion]) as source:
                index = big_index(source)
                for name, definition in resources:
                    entry = index.get(definition['member'])
                    if entry is None or not 0 < entry[1] <= LIMIT:
                        raise ValueError('Required BIG resource is absent or oversized')
                    source.seek(entry[0])
                    data = refpack(source.read(entry[1]), definition['size'])
                    if hashlib.sha256(data).hexdigest() != definition['sha256']:
                        raise ValueError('Original resource hash differs: ' + name)
                    target = stage / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open('xb') as output:
                        output.write(data)
                        output.flush()
                        os.fsync(output.fileno())
        receipt = {name: entry['sha256'] for name, entry in value['files'].items()}
        with (stage / 'complete.json').open('x') as output:
            json.dump(receipt, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(stage, root)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return str(root)
