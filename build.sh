#!/bin/sh
# Build dist/ignition-dev.apk. See docs/building.md.
set -e
cd "$(dirname "$0")"
exec python3 scripts/build_android_launcher.py "$@"
