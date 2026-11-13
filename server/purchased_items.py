"""Verified PurchasedItems empty-object response (run38).

Factory01034470 initializes both response vectors empty. Parser010345a8 has
no field-presence checks; callbacks guard all element loops. Run38 verifies
manager count -1→0 and empty installed inventory with FUT4/WebSession3 intact.
This establishes startup acceptance, not complete gameplay inventory semantics.
"""
from .identity import json_response

def response_for(method, target, headers, body):
    if (method == 'GET' and target == '/ut/game/fifaworldmobile/purchased/items'
            and headers.get(b'host') == b'10.0.2.2:18081'
            and headers.get(b'x-ut-sid') == b'fifa16-local-sid'
            and headers.get(b'content-length', b'0') == b'0' and body == b''):
        return json_response({})
    return None
