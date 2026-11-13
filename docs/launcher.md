# Using the launcher

16NITION opens to a home screen with **Play**, **Clubs**, **Setup** and
**GODMODE**. It works in portrait and landscape.

## Play

Starts the local server and opens the game with the last selected club. If
there is no club yet, Play opens the game's own club creation.

Your progress is saved automatically on the device, inside 16NITION's private
storage. The game also saves at its usual points. On a fresh club, the welcome
tutorial is marked done at the first progress save, for example when you open
Season Selection or Tournaments. If you quit before that, the welcome plays
again. The original game behaves the same way.

## Clubs

| Action | What it does |
|---|---|
| Select | Switch to another saved club. The other clubs stay untouched. |
| New club | Start a fresh club next to the existing ones. |
| Export club | Save a complete `.tar.gz` backup to a location you pick. It includes coins, items, packs, rewards and progress. |
| Import club | Load a backup from the file picker. The ownership of items and earned rewards is preserved. |

Export, import and switching are refused while a match is active or being
prepared. Finish or quit the match first. If the game is open, it closes itself
before the save is copied.

Backups are the way to move a club to another device or emulator, and the
only protection against uninstalling 16NITION.

## Setup

| Action | When to use it |
|---|---|
| Import expansions | First setup, or after replacing the OBB files |
| Prepare game | First setup, after a launcher update that asks for it, or to repair the game |

See [installation](installation.md) for details.

## GODMODE

Sets the selected club's balance to **999,999 FIFA Points (FP)**, which can be
spent on packs in the Store. Before changing anything it closes the game,
waits for the server to finish, and saves a full backup of the club in
16NITION's private storage. Press **Play** afterwards. Pressing it again at
999,999 FP does nothing. It is disabled while a club is still being set up.
Coins are not changed.
