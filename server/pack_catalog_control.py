"""Diagnostic empty StorePackTypes control, not a stock catalog or pack grant.

0230f82c accepts purchase[], constructor defaults safe for empty vector;
021ea6bc rebuilds zero groups and reports success. Explicit opt-in only.
"""
from .game_auth import SID
from .identity import json_response
PATH='/ut/game/fifaworldmobile/store/purchasegroup/all?ppInfo=true&categoryInfo=true'
def response_for(method,target,headers,body):
    if (method!='GET' or target!=PATH or body or headers.get(b'host')!=b'10.0.2.2:18081' or
        headers.get(b'x-ut-sid')!=SID.encode() or headers.get(b'content-length',b'0')!=b'0'):
        return None
    return json_response({'purchase':[]})
