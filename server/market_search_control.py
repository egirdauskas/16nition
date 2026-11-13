"""Isolated empty player-search control; no listings, currency or inventory.

415 captured the genuine default ISSearch request before any response. Factory
0230887c resets the result cache; parser02308e48 calls0102a320. RS4 key0x21 is
auctionInfo, whose empty array leaves the initialized result vector empty.
This diagnostic cannot implement populated search or any market transaction.
"""
from .game_auth import SID
from .identity import json_response

PATH = '/ut/game/fifaworldmobile/transfermarket?type=player&start=0&num=9'


def response_for(method, target, headers, body):
    if (method != 'GET' or target != PATH or body
            or headers.get(b'host') != b'10.0.2.2:18081'
            or headers.get(b'x-ut-sid') != SID.encode()
            or headers.get(b'content-length', b'0') != b'0'):
        return None
    return json_response({'auctionInfo': []})
