"""Prepare the local game copy from the user's original APK and the project recipe.

The bundle (game-recipe.zip) contains only project-authored material:
- recipe.json: per-version input/output SHA-256 pins and the DEX edit plan
  (routed strings are identified by the SHA-256 of the original value);
- holders.dex: the replacement method bodies, assembled from project smali;
- <versionCode>/shim.dex: the project startup shim classes.
No original game bytes, deltas or layout data are included. The caller supplies
`transform`, which runs org.ignition.recipe.DexRecipe (on the device through
Chaquopy, in the lab on the JVM). The manifest edits are game_manifest.edit.
Only classes.dex and AndroidManifest.xml change; every other entry is streamed
unchanged from the user's original.
"""
from copy import copy, deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import zipfile

from . import game_manifest

MEMBERS = ('classes.dex', 'AndroidManifest.xml')
LIMIT = 32 * 1024 * 1024
CLASSIFICATION = 'local_game_recipe'
_RECIPES = {}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def digest_file(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(262144), b''):
            value.update(block)
    return value.hexdigest()


def _hex(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _pinned_file(value):
    if (not isinstance(value, dict) or set(value) != {'path', 'sha256', 'size'}
            or not isinstance(value['path'], str) or not _hex(value['sha256'])
            or not isinstance(value['size'], int) or not 0 < value['size'] <= LIMIT):
        raise ValueError('Invalid game recipe file pin')


def _validate_dex(value):
    if not isinstance(value, dict) or set(value) != {'api', 'routes', 'methods'} or value['api'] != 24:
        raise ValueError('Invalid game recipe DEX plan')
    for route in value['routes']:
        if (set(route) != {'class', 'sha256', 'count', 'value'} or not _hex(route['sha256'])
                or not isinstance(route['count'], int) or route['count'] < 1):
            raise ValueError('Invalid game recipe route')
    for method in value['methods']:
        if set(method) != {'class', 'holder', 'name', 'prototype'}:
            raise ValueError('Invalid game recipe method')
    for line in plan_text(value).splitlines():
        if any(c in line for c in '\r\t') or '  ' in line:
            raise ValueError('Invalid game recipe plan text')


def plan_text(dex):
    """The line format read by DexRecipe.java."""
    lines = ['api ' + str(dex['api'])]
    for route in dex['routes']:
        lines.append(' '.join(['route', route['class'], route['sha256'], str(route['count']),
                               route['value']]))
    for method in dex['methods']:
        lines.append(' '.join(['method', method['class'], method['holder'], method['name'],
                               method['prototype']]))
    return '\n'.join(lines) + '\n'


def _validate_variant(code, value):
    keys = {'game_version', 'version_name', 'output_version_name', 'original', 'shim', 'output'}
    if not code.isdigit() or not isinstance(value, dict) or set(value) != keys:
        raise ValueError('Invalid game recipe variant')
    if not isinstance(value['game_version'], int) or not isinstance(value['version_name'], str):
        raise ValueError('Invalid game recipe variant')
    if set(value['original']) != set(MEMBERS) or not all(_hex(v) for v in value['original'].values()):
        raise ValueError('Invalid game recipe original pins')
    _pinned_file(value['shim'])
    if value['shim']['path'] != code + '/shim.dex':
        raise ValueError('Invalid game recipe shim path')
    if set(value['output']) != set(MEMBERS):
        raise ValueError('Invalid game recipe output pins')
    for name, pin in value['output'].items():
        if set(pin) != {'sha256', 'size'} or not _hex(pin['sha256']) or not 0 < pin['size'] <= LIMIT:
            raise ValueError('Invalid game recipe output pin')


def recipe(raw):
    """Validated recipe.json, memoized by content hash; returns a deep copy."""
    key = hashlib.sha256(raw).digest()
    if key not in _RECIPES:
        value = json.loads(raw)
        keys = {'version', 'classification', 'dex', 'holders', 'variants', 'legacy_patch_sha256'}
        if (not isinstance(value, dict) or set(value) != keys or value['version'] != 3
                or value['classification'] != CLASSIFICATION or not value['variants']):
            raise ValueError('Unsupported game recipe')
        _validate_dex(value['dex'])
        _pinned_file(value['holders'])
        if value['holders']['path'] != 'holders.dex':
            raise ValueError('Invalid game recipe holder path')
        if not all(_hex(item) for item in value['legacy_patch_sha256']):
            raise ValueError('Invalid legacy patch pin')
        for code, variant in value['variants'].items():
            _validate_variant(code, variant)
        if len(_RECIPES) >= 4:
            _RECIPES.clear()
        _RECIPES[key] = value
    return deepcopy(_RECIPES[key])


def _read_pinned(bundle, pin):
    info = bundle.getinfo(pin['path'])
    if info.file_size != pin['size']:
        raise ValueError('Game recipe file size differs')
    raw = bundle.read(pin['path'])
    if digest(raw) != pin['sha256']:
        raise ValueError('Game recipe file hash differs')
    return raw


def _expected_names(value):
    names = {'recipe.json', value['holders']['path']}
    names.update(variant['shim']['path'] for variant in value['variants'].values())
    return names


def build_members(original_members, value, code, bundle, transform):
    """Return the two edited members, each checked against its certified pin."""
    variant = value['variants'][str(code)]
    for name in MEMBERS:
        if digest(original_members[name]) != variant['original'][name]:
            raise ValueError('Original game member differs')
    shim = _read_pinned(bundle, variant['shim'])
    holders = _read_pinned(bundle, value['holders'])
    result = {
        'classes.dex': bytes(transform(original_members['classes.dex'], plan_text(value['dex']),
                                       shim, holders)),
        'AndroidManifest.xml': game_manifest.edit(
            original_members['AndroidManifest.xml'], original_version_code=int(code),
            original_version_name=variant['version_name'], version_code=variant['game_version'],
            version_name=variant['output_version_name']),
    }
    for name, raw in result.items():
        pin = variant['output'][name]
        if len(raw) != pin['size'] or digest(raw) != pin['sha256']:
            raise ValueError('Prepared game member differs')
    return result


def prepare(original, bundle, output, version_code, transform):
    original, bundle, output = Path(original), Path(bundle), Path(output)
    if output.resolve() in (original.resolve(), bundle.resolve()):
        raise ValueError('Original game files cannot be replaced')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.with_name(output.name + '.preparing')
    try:
        with zipfile.ZipFile(bundle) as package:
            value = recipe(package.read('recipe.json'))
            if set(package.namelist()) != _expected_names(value) or len(package.namelist()) != len(_expected_names(value)):
                raise ValueError('Game recipe file set differs')
            if str(int(version_code)) not in value['variants']:
                raise ValueError('Select a supported original FIFA 16 APK')
            try:
                source = zipfile.ZipFile(original)
            except zipfile.BadZipFile:
                raise ValueError('Select a supported original FIFA 16 APK')
            with source:
                try:
                    members = {name: source.read(name) for name in MEMBERS}
                except KeyError:
                    raise ValueError('Select a supported original FIFA 16 APK')
                changed = build_members(members, value, int(version_code), package, transform)
                with zipfile.ZipFile(stage, 'w') as result:
                    for entry in source.infolist():
                        if entry.filename.startswith('META-INF/'):
                            continue
                        info = copy(entry)
                        # Stored resources stay aligned for the original loader.
                        if info.compress_type == zipfile.ZIP_STORED:
                            position = (result.fp.tell() + 30 + len(info.filename.encode('utf-8'))
                                        + len(info.extra))
                            if position % 4:
                                padding = (-position - 4) % 4
                                info.extra += struct.pack('<HH', 0xd935, padding) + b'\0' * padding
                        with result.open(info, 'w') as destination:
                            if info.filename in changed:
                                destination.write(changed[info.filename])
                            else:
                                with source.open(entry) as stream:
                                    shutil.copyfileobj(stream, destination, 262144)
        with stage.open('rb') as ready:
            os.fsync(ready.fileno())
        os.replace(stage, output)
        variant = value['variants'][str(int(version_code))]
        return {'version': variant['game_version'], 'source_version_code': int(version_code),
                'original_sha256': digest_file(original), 'recipe_sha256': digest_file(bundle),
                'unsigned_sha256': digest_file(output), 'changed_members': sorted(MEMBERS)}
    finally:
        if stage.exists():
            stage.unlink()


def accepts(bundle, record):
    """True when a prepared-game record still matches this launcher's recipe.

    Games prepared by the earlier delta bundle stay valid: that bundle rebuilt
    the same certified build, so an update need not ask for the original again.
    """
    with zipfile.ZipFile(bundle) as package:
        value = recipe(package.read('recipe.json'))
    if record.get('recipe_sha256') == digest_file(bundle):
        return True
    return record.get('patch_sha256') in value['legacy_patch_sha256']
