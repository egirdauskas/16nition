# Installation

## Tested devices

FIFA 16 Mobile is a 32-bit ARM game, so the device or emulator must run
32-bit ARM apps. 16NITION itself needs Android 7.0 or newer.

| Device / emulator | Status |
|---|---|
| Android 9 emulator (Android Studio, ARM translation) | Reference device, fully tested |
| LDPlayer 14 (Windows) | Works end to end |
| Nox 7 (Windows) | Works end to end |
| MuMu Player, Android 12 player (Windows) | Works end to end |
| BlueStacks 5: Nougat 32-bit, Pie 64-bit, Android 13 (Windows) | Works end to end |
| MuMu Player, Android 15 player | **Not supported**: it has no 32-bit ARM support, so the game cannot install |
| Physical phones | Expected to work on devices with 32-bit ARM support; not formally tested |

Many recent phones (for example Pixel 7 and later) dropped 32-bit app support
and cannot run the game.

Windows emulators need a real GPU for good performance. 16:9, 16:10, 4:3 and
20:9 screens all render full screen.

## Game files

You need your own copy of the original game files:

| File | Version 3.2 (recommended) | Version 3.0 (experimental) |
|---|---|---|
| Game APK | FIFA 16 Mobile 3.2.113645 | FIFA 16 Mobile 3.0.112594 |
| Main expansion | `main.13.com.ea.gp.fifaworld.obb` | same |
| Patch expansion | `patch.26.com.ea.gp.fifaworld.obb` | `patch.22.com.ea.gp.fifaworld.obb` |

16NITION checks each file's checksum and the APK's original EA signature, and
refuses anything else **before** it changes anything on the device. Version 3.0
plays through setup and the tutorials; a few Store captions show on one line.

## First setup

1. **Install `16nition.apk`** from the [latest release](https://github.com/egirdauskas/16nition/releases/latest).
   Allow installs from your browser or file manager if Android asks.
2. **Copy the APK and both OBB files to the device.** Any folder works;
   `Download/16NITION` is a good choice. On emulators, drag and drop the files
   into the window or use its shared folder.
3. **Setup → Import expansions.** Select both OBB files in the file picker.
   16NITION verifies them and extracts the two small database files it needs.
   It reads the OBBs in place and does not make another full copy. If this
   is interrupted, just run it again.
4. **Prepare the game.** Tap **Play** or **Setup → Prepare game**:
   - **Choose original APK** and pick the APK file, or
   - **Use installed FIFA** if the original game is already installed.

   16NITION checks the original, applies its patch and signs the result with
   a key created on your device. Then approve Android's
   *install unknown apps* permission and the install dialog.

   If an original (EA-signed) FIFA 16 is already installed, Android will not
   let a differently signed copy replace it. 16NITION explains this and opens
   the uninstall dialog first. The old game's own data is removed, but your
   16NITION clubs are not touched.
5. **Play.** Tap **Play**. On first start, accept the game's storage
   permission: the game copies the OBB files into its own folder after
   checking them. Then create your club in the game.

You can also import a club backup (**Clubs → Import club**) before playing.

## Updating 16NITION

Install the new launcher APK over the old one. Your clubs and the prepared game
are kept. If a new version changes the game patch, 16NITION prepares the game
again with the same device key and updates it in place. Game data is kept.

> **Before uninstalling 16NITION or clearing its data, export your clubs.**
> The key that signs your prepared game lives inside 16NITION. Without it the
> game cannot be updated in place: it has to be uninstalled and prepared again,
> which removes the game's own data. Clubs that were exported can be imported
> again.

## What is installed

| App | Name on device | Contents |
|---|---|---|
| 16NITION | `org.ignition.launcher` | Launcher, the local server, your clubs |
| Prepared game | `com.ea.gp.fifaworld` | Your original game, patched to connect to 16NITION; signed on your device |

Nothing contacts EA's servers, and no system certificate, VPN profile or root
access is used.
