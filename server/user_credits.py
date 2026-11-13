"""GetUserCredits protocol adapter; state belongs to ProfileStore.

01041174 recognizes currencies[].name/funds. `coins` -> response+28,
01a5b1fc ->01a6f150 installs interface+cd0. Other response fields stay0.
"""
import json
from .local_profile import ProfileStore
from .game_auth import SID

PATH='/ut/game/fifaworldmobile/user/credits'

def encode(profile):
    currencies=[{'name':'coins','funds':profile.credits}]
    if profile.fifa_points:currencies.append({'name':'points','funds':profile.fifa_points})
    payload=json.dumps({'currencies':currencies},separators=(',',':')).encode()
    return (b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: '
            +str(len(payload)).encode()+b'\r\n\r\n'+payload)

def response_for(method,target,headers,body,store=None):
    if (method!='GET' or target!=PATH or body
        or headers.get(b'host')!=b'10.0.2.2:18081'
        or headers.get(b'x-ut-sid')!=SID.encode()):return None
    return encode((store or ProfileStore()).load())
