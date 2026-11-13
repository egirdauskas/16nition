# Building from source

## Requirements

- JDK 17 or newer
- Android SDK with platform 35 (set `ANDROID_HOME`, default `~/Android/Sdk`)
- Python 3.11 (the version bundled on the device by Chaquopy). If it is not
  your default `python3`, point the build at it:
  `export NITION_BUILD_PYTHON=/path/to/python3.11`
- Internet access on the first build (Gradle and Maven dependencies)

The original game files are **not** needed to build.

## Build

```sh
./build.sh
```

This produces `dist/ignition-dev.apk` and prints its SHA-256. The steps are:

1. Copy the prebuilt game recipe and content manifest from `prebuilt/` into
   the launcher assets.
2. Pack the Python server (`server/`, its policies and data) into
   `runtime.zip`, with a manifest of file hashes.
3. Build and sign the Android app with Gradle.

## Signing key

Builds are signed with a stable key at `~/.local/share/ignition/signing.p12`.
The configuration is in `signing.properties` next to it. On the first build
a new key is created automatically.

Android only installs an update when it is signed with the same key as the
installed app. **Keep that key private and back it up.** An APK built with a
different key cannot update an existing 16NITION install. Users would have to
uninstall, which loses their device game key; see
[installation](installation.md#updating-16nition).

The key never goes into the APK or the repository.

## Repository layout

| Path | Contents |
|---|---|
| `launcher/` | Android app: Java UI and services, `launcher.lua` layout, Python bridge |
| `launcher/game-shim/` | Small classes added to the user's game copy: localhost routing and launcher bootstrap |
| `server/` | Local game server (Python) with versioned `policy/` files for rewards, store, market and modes |
| `prebuilt/` | Game recipe (checksums, edit plan, project classes), content manifest and special-card catalog, generated in the development lab |
| `scripts/` | Build scripts and the docs table generator |
| `assets/branding/` | Launcher artwork |
| `docs/` | This documentation |

## Changing rewards or rules

Game rules and rewards live in `server/policy/*.json`. The server validates
each policy file strictly at load time, so a malformed change fails loudly
instead of paying out wrong amounts. After a change, regenerate the reference
tables and rebuild:

```sh
python3 scripts/generate_docs_tables.py
./build.sh
```

## Regenerating `prebuilt/`

The files in `prebuilt/` are created from the original game files with the
development tooling, which is not part of this repository. They only change
when support for a new game version is added.
