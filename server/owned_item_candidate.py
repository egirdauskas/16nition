"""Bounded one-item diagnostic, opt-in only; no durable account state yet.

010345a8 itemData[] ->01028fc0 ->01a63004 is observed inventory path.
Content identifiers come from a preserved local DB selection. The fixture does
not contain assets, player names/stats, history or invented club/account IDs.
"""
import json
from pathlib import Path
from .identity import json_response
from .game_auth import SID
from .local_profile import load_profile
PURCHASED='/ut/game/fifaworldmobile/purchased/items'
SQUAD='/ut/game/fifaworldmobile/squad/active?active=true'

def load_candidate(path):
 value=json.loads(Path(path).read_text())
 if set(value) != {'item','squad_slot'}:raise ValueError('Unexpected experiment state')
 item=value['item']
 if set(item)!={'id','resourceId','cardsubtypeid','lastSalePrice','teamid'}:raise ValueError('Unproved item fields')
 if type(item['id']) is not int or not 0<item['id']<=0x7fffffffffffffff:raise ValueError('Invalid instance ID')
 if type(item['resourceId']) is not int or not 0<item['resourceId']<=0xffffffff:raise ValueError('Invalid resource')
 if type(item['cardsubtypeid']) is not int or item['cardsubtypeid'] not in range(4):raise ValueError('Unproved subtype')
 if item['lastSalePrice']!=0 or type(item['lastSalePrice']) is not int:raise ValueError('No historical sale')
 if type(item['teamid']) is not int or not 0<item['teamid']<=200000:raise ValueError('Invalid locally linked team')
 slot=value['squad_slot']
 if slot is not None and (type(slot) is not int or not 0<=slot<23):raise ValueError('Invalid slot')
 return value

def response_for(method,target,headers,body,path):
 if (method!='GET' or target not in (PURCHASED,SQUAD) or body or
     headers.get(b'host')!=b'10.0.2.2:18081' or headers.get(b'x-ut-sid')!=SID.encode()):return None
 candidate=load_candidate(path)
 if target==PURCHASED:return json_response({'itemData':[candidate['item']]})
 if candidate['squad_slot'] is None:return None
 return json_response({'personaId':load_profile().persona_id,'players':[
  {'index':candidate['squad_slot'],'itemData':candidate['item']}]})
