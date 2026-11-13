"""Original FIFA 16 build served by this backend (on-device: the prepared game).

The store request carries no client version, so the launcher's prepared-game
record (`game-install/prepared.json`, `source_version_code`) is the source.
Records from before multi-version support, an absent record and the host lab
all mean the certified v26 build. Presentation differences between builds are
declared in server/data/ignition-game-versions-v1.json (outside the
server/policy fingerprint that pins Store/economy policy to fresh clubs).
"""

import json
from pathlib import Path

REFERENCE_VERSION = 26
_VERSION = REFERENCE_VERSION


def configure(prepared_record=None):
    """Select the build from a launcher prepared record; default v26."""
    global _VERSION
    version = REFERENCE_VERSION
    if prepared_record is not None and Path(prepared_record).is_file():
        record = json.loads(Path(prepared_record).read_bytes())
        version = int(record.get('source_version_code', REFERENCE_VERSION))
    from .game_versions import version as entry
    entry(version)  # unsupported builds fail closed at start
    _VERSION = version
    return version


def version_code():
    return _VERSION


def single_line_store_captions():
    """3.0's store tile header shows one line; v26 lays out stacked counts."""
    from .game_versions import version as entry
    return entry(_VERSION).get('store_caption_style') == 'single_line'


def single_line(short):
    """`12 ITEMS\\n4 GOLD\\n3 RARES` -> `12 items, 4 gold, 3 rares.` (EA's one-line style)."""
    lines = [line.strip() for line in short.split('\n') if line.strip()]
    return ', '.join(line.lower() for line in lines) + '.'
