#!/usr/bin/env python3
"""Build the project-owned Android runtime; never include accounts or EA assets."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'launcher/app/src/main/assets'
BASELINES = (
    'server/data/roster-control.json',
    'server/data/startup-control.json',
    'server/data/local-offline-definition.json',
    'server/data/local-content-references.json',
    # Supported original builds (install/presentation config, not Store policy).
    'server/data/ignition-game-versions-v1.json',
)


def runtime_files():
    tracked = subprocess.check_output(
        ['git', 'ls-files', '-z'], cwd=ROOT,
    ).decode().split('\0')
    files = {name for name in tracked if name.startswith('server/')
             and (name.endswith('.py') or name.startswith('server/policy/'))}
    files.discard('server/mobile_router.py')
    files.update(BASELINES)
    files.update({
        'assets/branding/pixel/16nition-v6-gift-872x520-light.png',
        'assets/branding/pixel/16nition-v6-launcher-512.png',
    })
    pending = [name for name in files if name.endswith('.py')]
    while pending:
        name = pending.pop()
        for node in ast.walk(ast.parse((ROOT / name).read_bytes())):
            module = node.module if isinstance(node, ast.ImportFrom) else None
            if module and module.startswith('scripts.'):
                source = module.replace('.', '/') + '.py'
                if source not in files:
                    files.add(source)
                    pending.append(source)
    return sorted(files)


def build():
    ASSETS.mkdir(parents=True, exist_ok=True)
    files = runtime_files()
    manifest = {'version': 1, 'classification': 'project_runtime', 'files': {}}
    destination = ASSETS / 'runtime.zip'
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            raw = (ROOT / name).read_bytes()
            manifest['files'][name] = hashlib.sha256(raw).hexdigest()
            entry = zipfile.ZipInfo(name, date_time=(2026, 11, 10, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, raw)
        # Compiled only after the unchanged historical validators pass.
        name = 'server/data/android-special-catalog.json'
        raw = (ROOT / 'prebuilt/android-special-catalog.json').read_bytes()
        manifest['files'][name] = hashlib.sha256(raw).hexdigest()
        entry = zipfile.ZipInfo(name, date_time=(2026, 11, 10, 0, 0, 0))
        entry.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(entry, raw)
    manifest['archive_sha256'] = hashlib.sha256(destination.read_bytes()).hexdigest()
    (ASSETS / 'runtime-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'files': len(files), 'bytes': destination.stat().st_size,
                      'sha256': manifest['archive_sha256']}))


if __name__ == '__main__':
    build()
