"""Diagnostic candidates only; no squad/item IDs or durable football model.

0230ea10/0102a998 support omitted fields and null preallocated references;
persona routes the parsed cache. These candidates must not be presented as
playable squads. Activation is explicitly opt-in pending downstream evidence.
"""
import json
from .game_auth import SID
from .local_profile import load_profile

PATH='/ut/game/fifaworldmobile/squad/active?active=true'
def response_for(method,target,headers,body,candidate):
 if (method!='GET' or target!=PATH or body or headers.get(b'host')!=b'10.0.2.2:18081'
     or headers.get(b'x-ut-sid')!=SID.encode()):return None
 if candidate=='empty':value={}
 elif candidate=='persona':value={'personaId':load_profile().persona_id}
 else:raise ValueError('Unproven ActiveSquad candidate')
 payload=json.dumps(value,separators=(',',':')).encode()
 return (b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: '
         +str(len(payload)).encode()+b'\r\n\r\n'+payload)
