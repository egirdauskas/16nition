"""Durable local item ownership, player condition and active squad references.

Account state contains instance/resource identifiers, occupied slots, observed
fitness and owned club items. Static card/team data stays in supplied content.
No invented squad ID, currency, trade history, names or statistics stored.
"""
from dataclasses import dataclass,asdict,replace
import hashlib,json,os,tempfile,fcntl
from contextlib import contextmanager
from pathlib import Path
from .local_content import ContentCatalog
from .policy_memo import fingerprint as policy_fingerprint
STATE_PATH=Path(__file__).parent/'data/local-football.json'
@dataclass(frozen=True)
class OwnedPlayerItem:
    instance_id:int
    resource_id:int
    fitness:int|None=None
    formation_id:int|None=None
    # Explicit local revival default, not recovered historical account state.
    morale:int=99
    # Wire training is a supplied training-card resource, not a stat total.
    training_resource_id:int|None=None
    # Historical version reference; never a fabricated special resource ID.
    special_version_id:str|None=None
    # Original preferredPosition override, separate from immutable card metadata.
    preferred_position:str|None=None
    # Original match-End injury data; absent on legacy healthy ownership rows.
    injury_type:str|None=None
    injury_games:int|None=None
@dataclass(frozen=True)
class OwnedManagerItem:
    instance_id:int
    resource_id:int
    # Account formation override, wire formation → native manager +5c.
    formation_id:int|None=None
@dataclass(frozen=True)
class OwnedConsumableItem:
    instance_id:int
    resource_id:int
@dataclass(frozen=True)
class SquadSlot:
    index:int
    instance_id:int
@dataclass(frozen=True)
class OwnedBadgeItem:
    instance_id:int
    resource_id:int
@dataclass(frozen=True)
class OwnedClubItem:
    instance_id:int
    resource_id:int
    item_type:str
@dataclass(frozen=True)
class ItemLocation:
    instance_id:int
    pile:str
@dataclass(frozen=True)
class ConsumableApplication:
    consumable_instance_id:int
    consumable_resource_id:int
    target_instance_id:int
@dataclass(frozen=True)
class SquadSummary:
    chemistry:int
    rating:int
    star_rating:int

def validate_squad_name(name):
    # Original Rename Squad dialog:3–15characters; Lua trims before saving.
    if (type(name) is not str or name != name.strip() or
        (name and (not 3<=len(name)<=15 or not all(c.isalnum() or c==' ' for c in name)))):
        raise ValueError('Invalid original squad name')
    return name

@dataclass(frozen=True)
class FootballState:
    persona_id:int
    owned_items:tuple=()
    active_lineup:tuple=()
    active_badge:OwnedBadgeItem|None=None
    active_club_items:tuple=()
    formation_id:int|None=None
    inventory_locations:tuple=()
    next_instance_id:int|None=None
    retired_instance_ids:tuple=()
    active_manager:OwnedManagerItem|None=None
    owned_consumables:tuple=()
    consumable_applications:tuple=()
    squad_name:str=''
    squad_summary:SquadSummary|None=None
    squad_id:int=0
    squad_manager_id:int|None=None
    other_squads:tuple=()
    squad_creations:tuple=()
    retired_squad_ids:tuple=()
    next_squad_id:int=1
    squad_native_id:int|None=None
    retired_native_squad_ids:tuple=()
    # Inactive club ownership is separate from the selected badge/kit/stadium.
    # Appended for compatibility with historical positional constructors.
    owned_club_items:tuple=()
    # Reward ownership restriction survives storage, application and retirement.
    # Empty legacy states retain their exact serialization schema.
    untradeable_instance_ids:tuple=()
    # Inactive managers (market purchases); the squad's manager stays active_manager.
    owned_managers:tuple=()

def owned_instance_ids(state):
    """All ownership keys; squad validation continues to use players only."""
    ids={i.instance_id for i in state.owned_items}
    if state.active_badge is not None:ids.add(state.active_badge.instance_id)
    if state.active_manager is not None:ids.add(state.active_manager.instance_id)
    ids|={i.instance_id for i in state.owned_managers}
    return ids|{i.instance_id for i in state.active_club_items}|{i.instance_id for i in state.owned_consumables+state.owned_club_items}

def club_manager_ids(state):
    """Managers usable in a squad: the active one and inactive ones in My Club."""
    ids={i.instance_id for i in state.owned_managers if item_pile(state,i.instance_id)=='club'}
    if state.active_manager is not None:ids.add(state.active_manager.instance_id)
    return ids

def activate_manager(state,manager_id):
    """Make an owned My Club manager the squad's active manager (swap; no ownership change)."""
    current=state.active_manager.instance_id if state.active_manager is not None else 0
    if manager_id in (0,current):return state
    chosen=next((m for m in state.owned_managers if m.instance_id==manager_id),None)
    if chosen is None or item_pile(state,manager_id)!='club':raise ValueError('Squad manager is not owned in My Club')
    rest=tuple(m for m in state.owned_managers if m.instance_id!=manager_id)
    if state.active_manager is not None:rest+=(state.active_manager,)
    return replace(state,active_manager=chosen,owned_managers=tuple(sorted(rest,key=lambda m:m.instance_id)))

def item_pile(state,instance_id):
    if instance_id not in owned_instance_ids(state):raise ValueError('Unknown owned instance')
    return next((p.pile for p in state.inventory_locations if p.instance_id==instance_id),'unassigned')

def validate(state,catalog):
    if type(state.persona_id) is not int or state.persona_id<=0:raise ValueError('Invalid owning local persona')
    validate_squad_name(state.squad_name)
    if state.squad_summary is not None:
        if (type(state.squad_summary) is not SquadSummary or
            any(type(v) is not int or not 0<=v<=100 for v in asdict(state.squad_summary).values())):
            raise ValueError('Invalid client-calculated squad summary')
    if state.formation_id is not None:
        from .local_formations import validate_formation
        validate_formation(state.formation_id)
    ids=set()
    for item in state.owned_items:
        from .injury_effects import validate_player
        validate_player(item)
        if type(item.instance_id) is not int or not 0<item.instance_id<=0x7fffffffffffffff:raise ValueError('Invalid instance ID')
        if item.instance_id in ids:raise ValueError('Duplicate instance identity')
        ids.add(item.instance_id);catalog.get(item.resource_id)
        if item.special_version_id is not None:
            from .reconstructed_specials import validate_reference
            validate_reference(item)
        if item.fitness is not None and (type(item.fitness) is not int or not 1<=item.fitness<=99):raise ValueError('Invalid player fitness')
        if type(item.morale) is not int or not 1<=item.morale<=99:raise ValueError('Invalid player morale')
        if item.training_resource_id is not None:
            from .local_consumables import validate_training_target
            validate_training_target(item.training_resource_id,item.resource_id)
        if item.formation_id is not None:
            from .local_formations import validate_formation
            validate_formation(item.formation_id)
        if item.preferred_position is not None:
            from .local_content_source import POSITION_WIRE,position_for
            if (item.preferred_position not in POSITION_WIRE.values() or
                    item.preferred_position=='GK' or position_for(item.resource_id)=='GK'):
                raise ValueError('Invalid player position modifier')
    slots=set();assigned=set()
    for slot in state.active_lineup:
        if type(slot.index) is not int or not 0<=slot.index<23:raise ValueError('Invalid squad slot')
        if slot.index in slots:raise ValueError('Duplicate occupied slot')
        if type(slot.instance_id) is not int or slot.instance_id not in ids:raise ValueError('Slot references unknown item')
        # Conservative local invariant; native duplicate-ID behavior is unproved.
        if slot.instance_id in assigned:raise ValueError('Item assigned twice')
        slots.add(slot.index);assigned.add(slot.instance_id)
    if state.active_badge is not None:
        from .local_content_source import badge_for
        badge=state.active_badge
        if type(badge.instance_id) is not int or not 0<badge.instance_id<=0x7fffffffffffffff or badge.instance_id in ids:raise ValueError('Invalid/duplicate badge instance')
        badge_for(badge.resource_id)
        ids.add(badge.instance_id)
    if (len(state.active_club_items)>4 or sum(i.item_type!='ball' for i in state.active_club_items)>3
        or sum(i.item_type=='ball' for i in state.active_club_items)>1):raise ValueError('Supported active club item bound exceeded')
    from .local_content_source import club_resource_for
    resources=set()
    for item in state.active_club_items:
        if type(item.instance_id) is not int or not 0<item.instance_id<=0x7fffffffffffffff or item.instance_id in ids:raise ValueError('Invalid/duplicate club instance')
        if item.item_type not in ('kit','stadium','ball'):raise ValueError('Unsupported active club item type')
        key=(item.item_type,item.resource_id)
        if key in resources:raise ValueError('Duplicate active club content')
        if item.item_type=='ball':
            from .local_club_items import reference
            reference(*key)
        else:club_resource_for(*key)
        resources.add(key);ids.add(item.instance_id)
    from .local_club_items import reference as club_card_reference
    for item in state.owned_club_items:
        if (type(item) is not OwnedClubItem or type(item.instance_id) is not int or
            not 0<item.instance_id<=0x7fffffffffffffff or item.instance_id in ids):
            raise ValueError('Invalid/duplicate inactive club ownership')
        club_card_reference(item.item_type,item.resource_id);ids.add(item.instance_id)
    located=set()
    from .local_consumables import inventory_reference as consumable_reference
    for item in state.owned_consumables:
        if type(item) is not OwnedConsumableItem or type(item.instance_id) is not int or not 0<item.instance_id<=0x7fffffffffffffff or item.instance_id in ids:
            raise ValueError('Invalid/duplicate consumable identity')
        consumable_reference(item.resource_id);ids.add(item.instance_id)
    if state.active_manager is not None:
        from .local_content_source import manager_for
        manager=state.active_manager
        if type(manager.instance_id) is not int or not 0<manager.instance_id<=0x7fffffffffffffff or manager.instance_id in ids:
            raise ValueError('Invalid/duplicate manager identity')
        manager_for(manager.resource_id)
        if manager.formation_id is not None:
            from .local_formations import validate_formation
            validate_formation(manager.formation_id)
        ids.add(manager.instance_id)
    for manager in state.owned_managers:
        from .local_content_source import manager_for
        if (type(manager) is not OwnedManagerItem or type(manager.instance_id) is not int
                or not 0<manager.instance_id<=0x7fffffffffffffff or manager.instance_id in ids):
            raise ValueError('Invalid/duplicate manager identity')
        manager_for(manager.resource_id)
        if manager.formation_id is not None:
            from .local_formations import validate_formation
            validate_formation(manager.formation_id)
        ids.add(manager.instance_id)
    for location in state.inventory_locations:
        if (type(location.instance_id) is not int or location.instance_id not in ids or
            location.instance_id in located or location.pile not in ('unassigned','club','trade')):
            raise ValueError('Invalid owned-item location')
        located.add(location.instance_id)
        if location.pile=='trade':
            if (location.instance_id in assigned or location.instance_id not in
                {i.instance_id for i in state.owned_items+state.owned_consumables+state.owned_club_items+state.owned_managers}):
                raise ValueError('Active squad/club items cannot enter transfer storage')
            consumable=next((i for i in state.owned_consumables if i.instance_id==location.instance_id),None)
            if consumable is not None and consumable_reference(consumable.resource_id)['cardsubtype']==233:
                raise ValueError('Free-pack vouchers cannot enter transfer storage')
    if state.next_instance_id is not None and (type(state.next_instance_id) is not int or
        not max(ids,default=0)<state.next_instance_id<=0x8000000000000000):
        raise ValueError('Invalid/exhausted local instance counter')
    retired=state.retired_instance_ids
    restricted=state.untradeable_instance_ids
    if (type(restricted) is not tuple or len(set(restricted))!=len(restricted) or
        any(type(i) is not int or i not in ids|set(retired) for i in restricted)):
        raise ValueError('Invalid untradeable ownership identity')
    if any(p.pile=='trade' and p.instance_id in restricted for p in state.inventory_locations):
        raise ValueError('Untradeable item cannot enter transfer storage')
    if (len(set(retired))!=len(retired) or any(type(i) is not int or not 0<i<=0x7fffffffffffffff or
        i in ids or state.next_instance_id is None or i>=state.next_instance_id for i in retired)):
        raise ValueError('Invalid retired ownership identity')
    receipts=set()
    from .consumable_effects import MAPPED_SUBTYPES,MANAGER_FORMATIONS,PLAYER_FORMATIONS,POSITION_PAIRS
    for receipt in state.consumable_applications:
        from .local_consumables import mapped_reference as reference
        if (type(receipt) is not ConsumableApplication or
            type(receipt.consumable_instance_id) is not int or receipt.consumable_instance_id not in retired or
            receipt.consumable_instance_id in receipts or
            type(receipt.target_instance_id) is not int or receipt.target_instance_id not in
            ({i.instance_id for i in state.owned_items}|
             ({state.active_manager.instance_id} if state.active_manager else set())|
             {m.instance_id for m in state.owned_managers}|set(retired)) or
            receipt.target_instance_id==receipt.consumable_instance_id or
            reference(receipt.consumable_resource_id)['cardsubtype'] not in MAPPED_SUBTYPES):
            raise ValueError('Invalid consumable application receipt')
        if receipt.target_instance_id not in retired:
            managers={m.instance_id for m in state.owned_managers}
            if state.active_manager is not None:managers.add(state.active_manager.instance_id)
            is_manager=receipt.target_instance_id in managers
            subtype=reference(receipt.consumable_resource_id)['cardsubtype']
            if is_manager!=(subtype in MANAGER_FORMATIONS):
                raise ValueError('Incompatible consumable application receipt')
            if subtype in PLAYER_FORMATIONS or subtype in POSITION_PAIRS:
                from .local_content_source import position_for
                player=next(i for i in state.owned_items if i.instance_id==receipt.target_instance_id)
                if position_for(player.resource_id)=='GK':raise ValueError('Incompatible player formation receipt')
        receipts.add(receipt.consumable_instance_id)
    from .local_squads import validate_bank
    validate_bank(state)
    return state

_LOAD_CACHE={}

class FootballStore:
    def __init__(self,path=None,catalog=None):
        self.path=Path(path or STATE_PATH);self.catalog=catalog or ContentCatalog()
    def load(self,persona_id):
        if not self.path.exists():return validate(FootballState(persona_id),self.catalog)
        raw=self.path.read_bytes()
        catalog_path=getattr(self.catalog,'path',None)
        if type(self.catalog) is not ContentCatalog or catalog_path is None or not Path(catalog_path).exists():
            return self.decode(json.loads(raw),persona_id)
        # PERF: decode+validate is a pure function of both files' bytes and the
        # persona; the decoded state is fully immutable (frozen dataclasses and
        # tuples), so the cached object is shared. Failures are not cached.
        key=(str(self.path.resolve()),hashlib.sha256(raw).digest(),
             hashlib.sha256(Path(catalog_path).read_bytes()).digest(),persona_id,policy_fingerprint())
        hit=_LOAD_CACHE.get(key)
        if hit is None:
            hit=self.decode(json.loads(raw),persona_id)
            if len(_LOAD_CACHE)>=8:_LOAD_CACHE.clear()
            _LOAD_CACHE[key]=hit
        return hit
    def decode(self,value,persona_id):
        """Validate a journal image without writing or changing live ownership."""
        if not {'persona_id','owned_items','active_lineup'}<=set(value) or set(value)-{'persona_id','owned_items','active_lineup','active_badge','active_club_items','formation_id','inventory_locations','next_instance_id','retired_instance_ids','active_manager','owned_consumables','consumable_applications','squad_name','squad_summary','squad_id','squad_manager_id','other_squads','squad_creations','retired_squad_ids','next_squad_id','squad_native_id','retired_native_squad_ids','owned_club_items','untradeable_instance_ids','owned_managers'}:raise ValueError('Unknown football state fields')
        from .local_squads import decode_record,SquadCreation
        state=FootballState(value['persona_id'],tuple(OwnedPlayerItem(**v) for v in value['owned_items']),
                            tuple(SquadSlot(**v) for v in value['active_lineup']),
                            OwnedBadgeItem(**value['active_badge']) if value.get('active_badge') is not None else None,
                            tuple(OwnedClubItem(**v) for v in value.get('active_club_items',[])),value.get('formation_id'),
                            tuple(ItemLocation(**v) for v in value.get('inventory_locations',[])),value.get('next_instance_id'),
                            tuple(value.get('retired_instance_ids',[])),
                            OwnedManagerItem(**value['active_manager']) if value.get('active_manager') is not None else None,
                            tuple(OwnedConsumableItem(**v) for v in value.get('owned_consumables',[])),
                            tuple(ConsumableApplication(**v) for v in value.get('consumable_applications',[])),
                            value.get('squad_name',''),
                            SquadSummary(**value['squad_summary']) if value.get('squad_summary') is not None else None,
                            value.get('squad_id',0),value.get('squad_manager_id'),
                            tuple(decode_record(v) for v in value.get('other_squads',[])),
                            tuple(SquadCreation(**v) for v in value.get('squad_creations',[])),
                            tuple(value.get('retired_squad_ids',[])),value.get('next_squad_id',1),value.get('squad_native_id'),
                            tuple(value.get('retired_native_squad_ids',value.get('retired_squad_ids',[]))),
                            tuple(OwnedClubItem(**v) for v in value.get('owned_club_items',[])),
                            tuple(value.get('untradeable_instance_ids',[])),
                            tuple(OwnedManagerItem(**v) for v in value.get('owned_managers',[])))
        validate(state,self.catalog)
        if state.persona_id!=persona_id:raise ValueError('Football state belongs to another persona')
        return state
    def save(self,state):
        validate(state,self.catalog);self.path.parent.mkdir(parents=True,exist_ok=True)
        value=self.encoded(state)
        fd,name=tempfile.mkstemp(prefix=self.path.name+'.',suffix='.new',dir=self.path.parent);tmp=Path(name)
        return self._write(state,value,fd,tmp)
    @staticmethod
    def encoded(state):
        """Exact JSON value save() writes (shared by multi-file intents)."""
        value={'persona_id':state.persona_id,
               'owned_items':[{k:v for k,v in asdict(i).items() if v is not None} for i in sorted(state.owned_items,key=lambda i:i.instance_id)],
               'active_lineup':[asdict(s) for s in sorted(state.active_lineup,key=lambda s:s.index)]}
        if state.formation_id is not None:value['formation_id']=state.formation_id
        if state.active_badge is not None:value['active_badge']=asdict(state.active_badge)
        if state.active_club_items:value['active_club_items']=[asdict(i) for i in state.active_club_items]
        if state.owned_club_items:value['owned_club_items']=[asdict(i) for i in sorted(state.owned_club_items,key=lambda i:i.instance_id)]
        if state.untradeable_instance_ids:value['untradeable_instance_ids']=sorted(state.untradeable_instance_ids)
        if state.owned_managers:value['owned_managers']=[{k:v for k,v in asdict(i).items() if v is not None} for i in sorted(state.owned_managers,key=lambda i:i.instance_id)]
        if state.inventory_locations:value['inventory_locations']=[asdict(i) for i in sorted(state.inventory_locations,key=lambda i:i.instance_id)]
        if state.next_instance_id is not None:value['next_instance_id']=state.next_instance_id
        if state.retired_instance_ids:value['retired_instance_ids']=sorted(state.retired_instance_ids)
        if state.active_manager is not None:value['active_manager']={k:v for k,v in asdict(state.active_manager).items() if v is not None}
        if state.owned_consumables:value['owned_consumables']=[asdict(i) for i in sorted(state.owned_consumables,key=lambda i:i.instance_id)]
        if state.consumable_applications:value['consumable_applications']=[asdict(i) for i in sorted(state.consumable_applications,key=lambda i:i.consumable_instance_id)]
        if state.squad_name:value['squad_name']=state.squad_name
        if state.squad_summary is not None:value['squad_summary']=asdict(state.squad_summary)
        if state.squad_id:value['squad_id']=state.squad_id
        if state.squad_manager_id is not None:value['squad_manager_id']=state.squad_manager_id
        if state.squad_native_id is not None:value['squad_native_id']=state.squad_native_id
        if state.retired_native_squad_ids:value['retired_native_squad_ids']=list(state.retired_native_squad_ids)
        if state.other_squads:value['other_squads']=[asdict(r) for r in state.other_squads]
        if state.squad_creations:value['squad_creations']=[asdict(r) for r in state.squad_creations]
        if state.retired_squad_ids:value['retired_squad_ids']=list(state.retired_squad_ids)
        if state.next_squad_id!=1:value['next_squad_id']=state.next_squad_id
        return value
    def _write(self,state,value,fd,tmp):
        try:
            with os.fdopen(fd,'w') as f:
                f.write(json.dumps(value,indent=2,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
            FootballStore(tmp,self.catalog).load(state.persona_id)
            tmp.replace(self.path)
            descriptor=os.open(self.path.parent,os.O_RDONLY)
            try:os.fsync(descriptor)
            finally:os.close(descriptor)
        finally:
            if tmp.exists():tmp.unlink()

    @contextmanager
    def transaction(self):
        """Serialize read/validate/replace across HTTP threads and local tools."""
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.with_name(self.path.name+'.lock').open('a') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)

    def update_squad(self,persona_id,lineup,formation_id,*,name=None,summary=None,manager_id=None):
        """Replace only squad composition/formation; ownership is untouched."""
        with self.transaction():
            current=self.load(persona_id)
            updated=replace(current,active_lineup=tuple(lineup),formation_id=formation_id)
            if manager_id is not None:updated=activate_manager(updated,manager_id)
            if name:
                # Empty legacy names cannot erase a genuine rename.
                updated=replace(updated,squad_name=validate_squad_name(name),squad_summary=summary)
            elif current.squad_name and summary is not None:
                updated=replace(updated,squad_summary=summary)
            validate(updated,self.catalog)
            if updated!=current:self.save(updated)
        return updated

    def preview_consumable_application(self,state,consumable_id,target_id,*,player_formation=False,extended_effects=frozenset()):
        """Validate this captured single-target family; retries have no effect."""
        if type(player_formation) is not bool:raise ValueError('Explicit player formation selector required')
        from .consumable_effects import FEATURES,PLAYER_FORMATIONS,MANAGER_FORMATIONS,POSITION_PAIRS,TRAINING_SUBTYPES,effective_position
        if type(extended_effects) is not frozenset or not extended_effects<=FEATURES:
            raise ValueError('Explicit admitted consumable effects required')
        if any(type(i) is not int or not 0<i<=0x7fffffffffffffff for i in (consumable_id,target_id)):
            raise ValueError('Invalid application identity')
        target=next((i for i in state.owned_items if i.instance_id==target_id),None)
        if state.active_manager is not None and state.active_manager.instance_id==target_id:target=state.active_manager
        if target is None:raise ValueError('Unknown/incompatible application target')
        if item_pile(state,target_id)=='trade':raise ValueError('Cannot modify transfer-listed target')
        receipt=next((i for i in state.consumable_applications if i.consumable_instance_id==consumable_id),None)
        if receipt:
            if receipt.target_instance_id!=target_id:raise ValueError('Consumed item belongs to another application')
            return state,target
        item=next((i for i in state.owned_consumables if i.instance_id==consumable_id),None)
        if item is None:raise ValueError('Unknown/already-consumed consumable')
        if item_pile(state,consumable_id)=='trade':raise ValueError('Cannot consume transfer-listed source')
        from .local_consumables import validate_training_target,inventory_reference as reference,mapped_effect as effect,INJURY_SUBTYPES
        subtype=reference(item.resource_id)['cardsubtype']
        if subtype in INJURY_SUBTYPES:
            if 'healing' not in extended_effects or type(target) is not OwnedPlayerItem:
                raise ValueError('Healing disabled/incompatible target')
            from .injury_effects import healing
            changed=healing(target,item.resource_id)
            target_delta={'owned_items':tuple(changed if i.instance_id==target_id else i for i in state.owned_items)}
        elif subtype in MANAGER_FORMATIONS:
            if subtype!=133 and 'manager_formation' not in extended_effects:raise ValueError('Manager formation disabled')
            if type(target) is not OwnedManagerItem:raise ValueError('Manager modifier requires an owned manager')
            field,value=effect(item.resource_id)
            changed=replace(target,**{field:value})
            target_delta={'active_manager':changed}
        elif subtype in PLAYER_FORMATIONS:
            from .local_content_source import position_for
            if not ('player_formation' in extended_effects or player_formation and subtype==78):raise ValueError('Player formation disabled by default')
            if type(target) is not OwnedPlayerItem or position_for(target.resource_id)=='GK':
                raise ValueError('Player formation requires owned non-goalkeeper')
            field,value=effect(item.resource_id)
            changed=replace(target,**{field:value})
            target_delta={'owned_items':tuple(changed if i.instance_id==target_id else i for i in state.owned_items)}
        elif subtype in POSITION_PAIRS:
            from .local_content_source import POSITION_WIRE
            if 'position' not in extended_effects or type(target) is not OwnedPlayerItem:
                raise ValueError('Player position disabled/incompatible')
            source_position,destination=map(POSITION_WIRE.__getitem__,POSITION_PAIRS[subtype])
            if effective_position(target)!=source_position:raise ValueError('Incompatible current player position')
            changed=replace(target,preferred_position=destination)
            target_delta={'owned_items':tuple(changed if i.instance_id==target_id else i for i in state.owned_items)}
        elif subtype in TRAINING_SUBTYPES:
            if subtype!=51 and 'training' not in extended_effects:raise ValueError('Training effect disabled')
            if type(target) is not OwnedPlayerItem:raise ValueError('GK training requires an owned player')
            validate_training_target(item.resource_id,target.resource_id)
            if target.training_resource_id is not None:raise ValueError('Replacing existing training is not yet captured')
            changed=replace(target,training_resource_id=item.resource_id)
            target_delta={'owned_items':tuple(changed if i.instance_id==target_id else i for i in state.owned_items)}
        else:raise ValueError('Unsupported consumable effect')
        updated=replace(state,
            **target_delta,
            owned_consumables=tuple(i for i in state.owned_consumables if i.instance_id!=consumable_id),
            inventory_locations=tuple(i for i in state.inventory_locations if i.instance_id!=consumable_id),
            retired_instance_ids=tuple(sorted(set(state.retired_instance_ids)|{consumable_id})),
            consumable_applications=tuple(sorted(state.consumable_applications+(ConsumableApplication(consumable_id,item.resource_id,target_id),),key=lambda i:i.consumable_instance_id)))
        return validate(updated,self.catalog),changed

    def apply_consumable(self,persona_id,consumable_id,target_id,*,player_formation=False,extended_effects=frozenset()):
        """One atomic save: target reference + retirement + retry receipt."""
        with self.transaction():
            current=self.load(persona_id)
            updated,player=self.preview_consumable_application(current,consumable_id,target_id,player_formation=player_formation,extended_effects=extended_effects)
            if updated!=current:self.save(updated)
            return player

    def mutate_inventory(self,persona_id,*,grants=(),remove_ids=(),locations=(),untradeable_grants=False):
        """Authoritative ownership/placement delta; no economy or squad edits.

        Player grants use already-validated content references. Club placement
        keeps the separate badge/kit/stadium models. Removing active players or
        active club items is rejected. Identical grants/moves are idempotent;
        absent removals cannot delete an unrelated object on a retry.
        """
        with self.transaction():
            current=self.load(persona_id)
            if type(untradeable_grants) is not bool:raise ValueError('Explicit ownership restriction required')
            players={i.instance_id:i for i in current.owned_items}
            consumables={i.instance_id:i for i in current.owned_consumables}
            club_items={i.instance_id:i for i in current.owned_club_items}
            ids=owned_instance_ids(current);active={s.instance_id for s in current.active_lineup}
            removals=tuple(remove_ids)
            if len(set(removals))!=len(removals) or any(type(i) is not int or not 0<i<=0x7fffffffffffffff for i in removals):
                raise ValueError('Invalid removal identity')
            if any(i in active or i in ids-set(players)-set(club_items) for i in removals):
                raise ValueError('Cannot remove active squad/club items')
            if any(i not in players and i not in club_items and i not in current.retired_instance_ids for i in removals):
                raise ValueError('Cannot remove an unknown ownership identity')
            additions=tuple(grants)
            if untradeable_grants and any(i.instance_id in ids and i.instance_id not in current.untradeable_instance_ids for i in additions):
                raise ValueError('Cannot retroactively restrict existing ownership')
            if any(type(i) not in (OwnedPlayerItem,OwnedConsumableItem,OwnedClubItem) for i in additions) or len({i.instance_id for i in additions})!=len(additions):
                raise ValueError('Invalid typed ownership grant')
            next_id=current.next_instance_id or max(ids,default=0)+1
            for item in additions:
                if item.instance_id in removals:raise ValueError('Conflicting ownership delta')
                objects=players if type(item) is OwnedPlayerItem else club_items if type(item) is OwnedClubItem else consumables
                if item.instance_id in ids and objects.get(item.instance_id)!=item:raise ValueError('Instance identity already owned')
                if item.instance_id not in ids and item.instance_id<next_id:raise ValueError('Cannot reuse allocated/retired identity')
                objects[item.instance_id]=item
                next_id=max(next_id,item.instance_id+1)
            for iid in removals:
                players.pop(iid,None);club_items.pop(iid,None)
            placements={i.instance_id:i for i in current.inventory_locations if i.instance_id not in removals}
            moves=tuple(locations)
            if any(type(i) is not ItemLocation for i in moves) or len({i.instance_id for i in moves})!=len(moves):
                raise ValueError('Invalid placement delta')
            placements.update((i.instance_id,i) for i in moves)
            updated=replace(current,owned_items=tuple(sorted(players.values(),key=lambda i:i.instance_id)),
                            owned_consumables=tuple(sorted(consumables.values(),key=lambda i:i.instance_id)),
                            owned_club_items=tuple(sorted(club_items.values(),key=lambda i:i.instance_id)),
                            inventory_locations=tuple(sorted(placements.values(),key=lambda i:i.instance_id)),
                            untradeable_instance_ids=tuple(sorted(set(current.untradeable_instance_ids)|({i.instance_id for i in additions} if untradeable_grants else set()))),
                            next_instance_id=next_id if additions or removals else current.next_instance_id,
                            retired_instance_ids=tuple(sorted(set(current.retired_instance_ids)|set(removals))))
            validate(updated,self.catalog)
            if updated!=current:self.save(updated)
            return updated

    def grant_consumables(self,persona_id,resource_ids,*,pile='club',prepare=None):
        """Explicit audited test grant using the shared monotonic ownership space."""
        resources=tuple(resource_ids)
        if not resources or len(resources)>100 or pile not in ('club','unassigned'):raise ValueError('Invalid consumable grant')
        with self.transaction():
            current=self.load(persona_id)
            first=current.next_instance_id or max(owned_instance_ids(current),default=0)+1
            items=tuple(OwnedConsumableItem(first+n,rid) for n,rid in enumerate(resources))
            updated=replace(current,owned_consumables=current.owned_consumables+items,next_instance_id=first+len(items),
                inventory_locations=current.inventory_locations+tuple(ItemLocation(i.instance_id,pile) for i in items))
            validate(updated,self.catalog)
            if prepare is not None:prepare(items)
            self.save(updated)
            return items

    def grant_mixed_items(self,persona_id,factory,*,prepare=None,untradeable=False):
        """One shared allocation/save for player+consumable pack contents.

        Factory receives the next monotonic ID under the existing ownership
        lock. The pack's existing prepared receipt is saved before ownership.
        """
        with self.transaction():
            if type(untradeable) is not bool:raise ValueError('Explicit ownership restriction required')
            current=self.load(persona_id)
            first=current.next_instance_id or max(owned_instance_ids(current),default=0)+1
            items=tuple(factory(first))
            if (not 1<=len(items)<=100 or
                any(type(i) not in (OwnedPlayerItem,OwnedConsumableItem,OwnedClubItem) or i.instance_id!=first+n for n,i in enumerate(items)) or
                any((i.fitness,i.morale)!=(99,99) for i in items if type(i) is OwnedPlayerItem)):
                raise ValueError('Invalid mixed allocation/condition')
            updated=replace(current,owned_items=current.owned_items+tuple(i for i in items if type(i) is OwnedPlayerItem),
                owned_consumables=current.owned_consumables+tuple(i for i in items if type(i) is OwnedConsumableItem),
                owned_club_items=current.owned_club_items+tuple(i for i in items if type(i) is OwnedClubItem),
                untradeable_instance_ids=tuple(sorted(set(current.untradeable_instance_ids)|({i.instance_id for i in items} if untradeable else set()))),
                next_instance_id=first+len(items),
                inventory_locations=current.inventory_locations+tuple(ItemLocation(i.instance_id,'unassigned') for i in items))
            validate(updated,self.catalog)
            if prepare is not None:prepare(items)
            self.save(updated)
            return items

    def grant_player(self,persona_id,resource_id,fitness=99):
        """Allocate one local owned instance from an existing content reference.

        This internal operation has no pack/economy/reward policy. Persisting
        the next ID prevents reuse even after a later deletion and restart.
        """
        return self.grant_players(persona_id,(resource_id,),fitness=fitness)[0]

    def grant_players(self,persona_id,resource_ids,*,fitness=99,formation_id=None,formation_ids=None,special_version_ids=None,prepare=None):
        """Reuse monotonic ownership allocation for one durable batch.

        prepare(items), if supplied, journals the exact allocation while the
        existing ownership lock is held and BEFORE the atomic ownership save.
        Pack recovery replays the same identities through mutate_inventory.
        No active squad/club/manager/account economy is changed.
        """
        # Legacy callers may explicitly omit condition; new ownership is always
        # full-condition. Refuse lower or malformed grants before allocation.
        if fitness is None:fitness=99
        if type(fitness) is not int or fitness!=99:raise ValueError('Offline player grants require fitness99')
        resources=tuple(resource_ids)
        if not resources or len(resources)>100:raise ValueError('Invalid grant batch')
        formations=tuple(formation_ids) if formation_ids is not None else (formation_id,)*len(resources)
        if len(formations)!=len(resources) or (formation_ids is not None and formation_id is not None):raise ValueError('Invalid grant formation batch')
        versions=tuple(special_version_ids) if special_version_ids is not None else (None,)*len(resources)
        if len(versions)!=len(resources):raise ValueError('Invalid special-version batch')
        with self.transaction():
            current=self.load(persona_id)
            first=current.next_instance_id or max(owned_instance_ids(current),default=0)+1
            items=tuple(OwnedPlayerItem(first+n,rid,fitness,formations[n],special_version_id=versions[n]) for n,rid in enumerate(resources))
            updated=replace(current,owned_items=current.owned_items+items,next_instance_id=first+len(items))
            validate(updated,self.catalog)
            if prepare is not None:prepare(items)
            self.save(updated)
            return items

    def configure_manager_and_player_formations(self,persona_id,manager_resource_id,player_formation_id):
        """Explicit local account customization, no consumable/economy policy.

        Keep current squad layout and all ownership/conditions. The manager is
        separate from players/club actives. Repeating the same request keeps
        the manager identity and does not grant duplicates or reset anything.
        """
        from .local_formations import validate_formation
        from .local_content_source import manager_for
        validate_formation(player_formation_id);manager_for(manager_resource_id)
        with self.transaction():
            current=self.load(persona_id);manager=current.active_manager
            next_id=current.next_instance_id or max(owned_instance_ids(current),default=0)+1
            if manager is not None and manager.resource_id!=manager_resource_id:
                raise ValueError('Replacing an existing manager is not a proven ownership path')
            if manager is None:
                manager=OwnedManagerItem(next_id,manager_resource_id);next_id+=1
            placements={i.instance_id:i for i in current.inventory_locations}
            placements[manager.instance_id]=ItemLocation(manager.instance_id,'club')
            updated=replace(current,owned_items=tuple(replace(i,formation_id=player_formation_id) for i in current.owned_items),
                            active_manager=manager,next_instance_id=next_id,
                            inventory_locations=tuple(sorted(placements.values(),key=lambda i:i.instance_id)))
            validate(updated,self.catalog)
            if updated!=current:self.save(updated)
            return updated
