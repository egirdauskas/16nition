# How it works

```
 ┌──────────────────────── Android device ────────────────────────┐
 │                                                                 │
 │  16NITION launcher (org.ignition.launcher)                      │
 │   ├─ UI (Java + launcher.lua)                                   │
 │   ├─ Local server (Python via Chaquopy, from runtime.zip)       │
 │   │    └─ clubs in private files/saves/                         │
 │   └─ Game preparation (recipe + on-device signing key)          │
 │              ▲  loopback only (127.0.0.1)                       │
 │              │                                                  │
 │  Prepared game (com.ea.gp.fifaworld)                            │
 │   ├─ original code, art, native libraries and OBB data          │
 │   └─ game-shim: routes server requests to the launcher          │
 └─────────────────────────────────────────────────────────────────┘
```

## Preparation

The launcher never ships the game. On the device it:

1. checks that the user's APK is an original EA-signed, supported version;
2. rebuilds `classes.dex` and `AndroidManifest.xml` from the user's own
   copies using `game-recipe.zip`. The recipe holds only checksums, an edit
   plan, the game-shim classes and three replacement method bodies; it
   contains no bytes of the original game. `DexRecipe` (dexlib2) swaps the
   game's server addresses for the local server, replaces three
   connectivity methods and adds the shim; `server/game_manifest.py` makes
   the matching manifest edits. Both results must match certified
   checksums. Native libraries, art and the resource table stay
   byte-identical;
3. signs the result with a key generated in Android's keystore on that
   device, which can never be exported;
4. hands the APK to Android's normal installer.

The launcher and the game check each other's identity (package, UID and
certificate) before they talk, so another app cannot impersonate either.

## The local server

The Python server implements the game's online services: login, club, squad,
Seasons, Tournaments, Store, Transfer Market and rewards. It runs inside the
launcher and listens only on the loopback interface.

Rewards are written atomically together with the match or purchase that
earned them. Each grant is recorded with its source, so retries never pay
twice, and an interrupted match is rolled back cleanly.

All rules and amounts come from versioned JSON files in `server/policy/`.
The [reference tables](README.md#reference-tables) are generated from them.
