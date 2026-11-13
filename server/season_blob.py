"""Stock legacy season record vectors; no player/result interpretation.

0101b5dc writes the legacy header, 24-byte player records and 128-byte match
records; 0101ac58 reloads it. Only count/TP header and structural sizes are
used. The rest is preserved, never applied to profile/football state.
"""
import struct
import zlib

POSTMATCH_SIZE = 575
PLAYER_RECORDS = 18
# 0101b5dc writes the vector's count as one byte, then copies its24-byte
# records. It is cumulative across fixtures/changed squads: genuine903 has36.
# This is a format bound, not an18/19-player roster whitelist.
MAX_PLAYER_RECORDS = 255
SUPPORTED_PLAYER_RECORDS = range(1, MAX_PLAYER_RECORDS + 1)
MAX_MATCHES = 10  # Both supported local definitions have ten stock fixtures.

def payload_size(matches, players=PLAYER_RECORDS):
    return 15 + 24 * players + 128 * matches

SUPPORTED_SIZES = frozenset((15, *(payload_size(n, players)
    for players in SUPPORTED_PLAYER_RECORDS for n in range(1, MAX_MATCHES + 1))))

def decode_envelope(wire):
    if not isinstance(wire, bytes) or len(wire) < 4:
        raise ValueError('Invalid season envelope')
    size = struct.unpack('<I', wire[:4])[0]
    if size not in SUPPORTED_SIZES:
        raise ValueError('Unsupported bounded legacy season vector size')
    payload = wire[4:]
    if len(payload) == size:
        return payload
    if len(payload) >= size or not payload.startswith(b'\x1f\x8b'):
        raise ValueError('Invalid native compression envelope')
    try:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        raw = decoder.decompress(payload, size + 1)
    except zlib.error as exc:
        raise ValueError('Invalid season gzip') from exc
    if len(raw) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('Season length/CRC/trailing-data mismatch')
    return raw

def validated_progress(raw, round_number):
    if type(round_number) is not int:
        raise ValueError('Invalid round type')
    if round_number == 1 and raw == bytes(15):
        return 0
    matches = round_number - 1
    players=raw[7] if len(raw)>=8 else None
    if not 1 <= matches <= MAX_MATCHES or players not in SUPPORTED_PLAYER_RECORDS or len(raw) != payload_size(matches,players):
        raise ValueError('Round and bounded legacy record size disagree')
    # Legacy (no optional 0010/version header), MP, TP and nPR/nMR positions
    # from the actual writer and loader. No stats/player fields are decoded.
    if raw[:4] != bytes(4) or raw[4] != matches:
        raise ValueError('Unsupported stock season header/counts')
    match_count_at = 11 + raw[7] * 24
    if raw[match_count_at] != matches or len(raw) != 15 + 24 * raw[7] + 128 * raw[match_count_at]:
        raise ValueError('Invalid native season record boundaries')
    return raw[5]  # named TP in0101ac58; copied to model+2d by both paths
