"""Scoped candidates for the captured ResetMatch operation.

Factory0230a868 defaults response+0x28 to false; parser0230a968 reads 'reset'.
The active frontend021fd6c0 depends on result+0x10, not that optional boolean.
Run33 rejects an empty HTTP200 body for progression; run34 proves HTTP200 {}.
The empty candidate is retained only for explicit experiment reproduction.
"""
from .identity import json_response

def response_for(method, target, headers, body, candidate):
    if not (method == 'PUT' and target == '/ut/game/fifaworldmobile/match/reset'
            and headers.get(b'host') == b'10.0.2.2:18081'
            and headers.get(b'x-ut-sid') == b'fifa16-local-sid'
            and headers.get(b'content-length') == b'0' and body == b''):
        return None
    if candidate == 'empty':
        return (b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                b'Content-Length: 0\r\nConnection: close\r\n\r\n')
    if candidate == 'object':
        return json_response({})
    return None
