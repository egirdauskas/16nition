#!/usr/bin/env python3
"""Build the branded APK, with on-device Python and no original game files."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    from ignition_signing import configuration
    configuration()
    sdk = Path(os.environ.get('ANDROID_HOME', Path.home() / 'Android/Sdk'))
    native = ROOT / 'launcher/app/src/main/jniLibs'
    if native.exists():
        shutil.rmtree(native)
    # The game recipe and content manifest are generated in the lab (the
    # recipe is certified there against the originals); shipped prebuilt.
    assets = ROOT / 'launcher/app/src/main/assets'
    assets.mkdir(parents=True, exist_ok=True)
    for name in ('game-recipe.zip', 'content-manifest.json'):
        shutil.copyfile(ROOT / 'prebuilt' / name, assets / name)
    stale = assets / 'game-patch.zip'
    if stale.exists():
        stale.unlink()
    subprocess.run(['python3', 'scripts/build_android_runtime.py'], cwd=ROOT, check=True)
    env = dict(os.environ, ANDROID_HOME=str(sdk))
    subprocess.run(['./gradlew', '--no-daemon', '--console=plain', 'assembleDebug'],
                   cwd=ROOT / 'launcher', env=env, check=True)
    output = ROOT / 'dist/ignition-dev.apk'
    output.parent.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / 'launcher/app/build/outputs/apk/debug/app-debug.apk', output)
    print(str(output))
    print('sha256 ' + hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
