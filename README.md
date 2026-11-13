# 16NITION

Local, feature-complete FIFA 16 Mobile backend for arm32 devices.

16NITION brings FIFA 16 Mobile (Ultimate Team) back fully offline. It is an
Android launcher that runs a replacement game server on the device itself and
prepares your own copy of the original game to talk to it. No account, VPN,
root or certificate install is needed.

It includes Seasons, Tournaments, the Store, the Transfer Market, levels,
accomplishments and club backups. See the [docs](docs/README.md) for the full
rules and reward tables.

## What you need

- An Android device or emulator that can run **32-bit ARM** apps, Android 7.0
  or newer. Tested emulators are listed in
  [docs/installation.md](docs/installation.md#tested-devices).
- Your own copy of the original FIFA 16 Mobile files. The game is not included:
  - the original APK, version **3.2.113645** (recommended) or **3.0.112594**
    (experimental);
  - the matching expansion files: `main.13.com.ea.gp.fifaworld.obb` and
    `patch.26.com.ea.gp.fifaworld.obb` (or `patch.22.com.ea.gp.fifaworld.obb`
    for 3.0).
- About 4 GB of free storage. The game files are about 1.5 GB, and the game
  copies them into its own folder once.

## Installation

1. **Install the launcher.** Download `16nition.apk` from the
   [latest release](https://github.com/egirdauskas/16nition/releases/latest) and install it. If Android asks,
   allow installing apps from your browser or file manager.
2. **Copy the game files to the device**, for example into
   `Download/16NITION`: the original APK and both OBB files.
3. **Import the expansions.** Open 16NITION → **Setup → Import expansions**
   and select the `main` and `patch` OBB files. 16NITION checks them and
   prepares its database.
4. **Prepare the game.** Tap **Play** (or **Setup → Prepare game**), then
   **Choose original APK** and select the APK. If the original game is
   already installed, use **Use installed FIFA** instead. Approve Android's
   install prompts.
   - If an original FIFA 16 is already installed, Android has to remove it
     first. 16NITION explains this and opens the uninstall dialog. Your
     16NITION clubs are kept, but the old game's own data is removed.
5. **Play.** Tap **Play**, accept the game's storage permission, and
   create your club in the game. You get a starting squad, a welcome gift and
   a 1-coin Starter Pack in the Store.

The full guide, including emulator setup and updates, is in
[docs/installation.md](docs/installation.md). If something goes wrong, see
[troubleshooting](docs/troubleshooting.md).

## Updating

Install the new `16nition.apk` over the old one. Clubs and the prepared game
stay. **Do not uninstall 16NITION or clear its data** without exporting your
clubs first (**Clubs → Export club**). Either one removes the key that links
the launcher to the prepared game, and the game then has to be replaced.

## Building from source

```sh
./build.sh          # writes dist/ignition-dev.apk
```

Needs JDK 17 or newer, Android SDK 35 and Python 3.11. See
[docs/building.md](docs/building.md).

## Legal

The game itself is not included: you supply your own copy, and 16NITION
modifies only that copy, on your device. EA SPORTS is a trademark of Electronic Arts
Inc.; FIFA is a trademark of FIFA. This project is not affiliated with or
endorsed by either. It is non-commercial.
16NITION's own code is licensed under the GNU GPL v3 ([LICENSE](LICENSE)).
Bundled third-party notices are in `launcher/app/src/main/assets/`.
