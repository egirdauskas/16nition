"""Bounded current-ID0 list candidate, parser0230dea8/record010261c8.

Supplied Squad.lua requires a matching current ID before LoadSquadById.
Existing sparse ActiveSquad cache has ID0. No new account/squad ID generated.
Record name/formation/rating/chemistry remain constructor defaults.
"""
from .identity import json_response
PATH='/ut/game/fifaworldmobile/squad/list'
def response_for(method,target,headers,body,football_store=None):
 if (method=='GET' and target==PATH and headers.get(b'host')==b'10.0.2.2:18081'
     and headers.get(b'x-ut-sid')==b'fifa16-local-sid' and not body
     and headers.get(b'content-length',b'0')==b'0'):
  values=[{'id':0}]
  if football_store is not None:
   from .local_profile import load_profile
   from .local_formations import FORMATIONS
   state=football_store.load(load_profile().persona_id)
   from .local_squads import native_records,active_record,wire_id
   from .squad_management import selected
   values=[]
   for record in native_records(state) if selected(football_store) else (active_record(state),):
    value={'id':wire_id(record) if selected(football_store) else record.id}
    if record.name or selected(football_store):value['squadName']=record.name
    if record.summary is not None:value.update(chemistry=record.summary.chemistry,rating=record.summary.rating)
    elif selected(football_store):value.update(chemistry=0,rating=0)
    if record.formation_id is not None:value['formation']=FORMATIONS[record.formation_id]
    elif selected(football_store):value['formation']=FORMATIONS[23]
    values.append(value)
  return json_response({'squad':values})
 return None
