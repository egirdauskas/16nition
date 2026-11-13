"""Exact captured full SaveSquad edit adapter, separate from durable ownership.

Derived chemistry/rating remain client-calculated. Existing manager identity
is retained; this adapter does not grant, replace or remove managers. Captured
names and client-calculated aggregate summaries survive canonical readback.
"""
from dataclasses import dataclass
import json
from .local_football import SquadSlot,SquadSummary,validate_squad_name
from .local_formations import FORMATIONS

WIRE_FORMATIONS={wire:identifier for identifier,wire in FORMATIONS.items()}
FIELDS={'id','squadName','chemistry','starRating','rating','formation','manager','players'}

@dataclass(frozen=True)
class SquadUpdate:
    lineup:tuple
    formation_id:int
    name:str
    summary:SquadSummary
    squad_id:int
    manager_id:int


def decode(body,state,*,squad_id=0,create=False,management=False):
    value=json.loads(body)
    if type(value) is not dict or set(value)!=FIELDS:raise ValueError('Unmapped full squad edit')
    if type(value['id']) is not int or not 0<=value['id']<0x7fffffff or value['id']!=squad_id:raise ValueError('Squad identity differs from request')
    if squad_id!=0 and not management:raise ValueError('Named squad management disabled')
    validate_squad_name(value['squadName'])
    for key in ['chemistry','starRating','rating']:
        if type(value[key]) is not int or not 0<=value[key]<=100:raise ValueError('Invalid derived squad scalar')
    if type(value['formation']) is not str or value['formation'] not in WIRE_FORMATIONS:raise ValueError('Unknown formation wire identifier')
    manager=value['manager']
    manager_id=state.active_manager.instance_id if state.active_manager is not None else 0
    # The active manager, or another owned manager in My Club (swapped in on save).
    from .local_football import club_manager_ids
    allowed=club_manager_ids(state)|({0} if management else set())
    if not allowed:allowed={manager_id}
    if (type(manager) is not list or len(manager)!=1 or type(manager[0]) is not dict or
        set(manager[0])!={'id'} or type(manager[0]['id']) is not int or manager[0]['id'] not in allowed):raise ValueError('Manager mutation not supported')
    players=value['players']
    if type(players) is not list or len(players) not in ((0,23) if create else (23,)):raise ValueError('Full edit requires23 explicit slots, or captured empty creation')
    owned={item.instance_id for item in state.owned_items} # Excludes badge/kit/stadium ownership.
    indices=set();assigned=set();lineup=[]
    for player in players:
        if type(player) is not dict or set(player)!={'index','itemData'}:raise ValueError('Unmapped slot structure')
        index=player['index'];item=player['itemData']
        if type(index) is not int or not 0<=index<23 or index in indices:raise ValueError('Invalid/duplicate slot')
        indices.add(index)
        if type(item) is not dict or set(item)!={'id'} or type(item['id']) is not int:raise ValueError('Slot requires instance ID only')
        iid=item['id']
        if iid==0:continue # Native empty-slot sentinel; never an owned instance.
        if iid not in owned or iid in assigned:raise ValueError('Unknown/non-player/duplicate assigned instance')
        assigned.add(iid);lineup.append(SquadSlot(index,iid))
    return SquadUpdate(tuple(sorted(lineup,key=lambda slot:slot.index)),WIRE_FORMATIONS[value['formation']],value['squadName'],SquadSummary(value['chemistry'],value['rating'],value['starRating']),value['id'],manager[0]['id'])
