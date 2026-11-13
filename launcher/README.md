# Launcher

Android app for 16NITION (package `org.ignition.launcher`). It hosts the local
Python server, prepares the user's game copy and manages clubs.

- Layout, labels and colours: `app/src/main/assets/ui/launcher.lua` (LuaJ 3.0.1)
- Java UI and services: `app/src/main/java/org/ignition/launcher/`
- Python bridge to the server: `app/src/main/python/launcher_bridge.py`
- Classes added to the game copy: `game-shim/`

Build from the repository root with `./build.sh`; see
[docs/building.md](../docs/building.md). User documentation starts at
[docs/README.md](../docs/README.md).
