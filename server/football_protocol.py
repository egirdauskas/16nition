"""Only observed PurchasedItems and ActiveSquad adapters for local item state.

Shared decoder creates/updates a full record even on an existing instance ID;
therefore squad itemData repeats canonical record metadata, not ID-only data.
lastSalePrice=0 initializes unsafe scratch+30; it is not persisted trade history.
"""
from .game_auth import SID
from .identity import json_response
from .local_profile import load_profile
from .local_football import FootballStore,item_pile
PURCHASED='/ut/game/fifaworldmobile/purchased/items'
SQUAD='/ut/game/fifaworldmobile/squad/active?active=true'
def encode_badge(item):
    #01030a0c: custom→subtype11;01a3e37c→class7;01027c20→local fcc_badgecards.
    return {'id':item.instance_id,'resourceId':item.resource_id,'itemType':'custom','cardsubtypeid':11,'lastSalePrice':0}
def encode_club_item(item):
    from .local_club_items import SUBTYPES
    return {'id':item.instance_id,'resourceId':item.resource_id,'itemType':item.item_type,
            'cardsubtypeid':SUBTYPES[item.item_type],'lastSalePrice':0}

def encode_owned_club_item(item,account=None):
    # Badges use the original custom11 wire type; ball30 is explicit, so no
    # unknown training-card alias or player attributes enter the decoder.
    value=encode_badge(item) if item.item_type=='badge' else encode_club_item(item)
    from .native_quick_sell_protocol import project_item
    return project_item(value,item,account)
def encode_actives(state):
    values=[encode_badge(state.active_badge)] if state.active_badge is not None else []
    values += [encode_club_item(item) for item in state.active_club_items]
    for value in values:
        if value['id'] in state.untradeable_instance_ids:value.update(untradeable=True,discardValue=0)
    return values
def encode_manager(item):
    #01030a0c manager→subtype4;01a3e37c→class2;01028668→managercards.
    from .local_content_source import manager_for
    from .local_formations import FORMATIONS
    ref=manager_for(item.resource_id)
    value={'id':item.instance_id,'resourceId':item.resource_id,'cardsubtypeid':4,'lastSalePrice':0,
           'rating':ref['value']}
    formation=item.formation_id if item.formation_id is not None else ref['formationid']
    if formation in FORMATIONS:value['formation']=FORMATIONS[formation]
    return value
CONSUMABLE_DISPLAY_ACCOUNT=None

def configure_consumable_display(account=None):
    """Explicit Store/isolated display only; no consumable effect admission."""
    global CONSUMABLE_DISPLAY_ACCOUNT
    if account is None:CONSUMABLE_DISPLAY_ACCOUNT=None;return
    from pathlib import Path
    from .store_release import projection_account
    account=Path(account).resolve()
    validated=projection_account([account/name for name in ('profile.json','football.json','content.json','packs.json','seasons.json','definition.json','control.json')])
    CONSUMABLE_DISPLAY_ACCOUNT=validated

def encode_consumable(item,account=None):
    from .local_consumables import inventory_reference as reference
    ref=reference(item.resource_id)
    from .local_consumables import inventory_references
    if item.resource_id not in inventory_references():
        from pathlib import Path
        if CONSUMABLE_DISPLAY_ACCOUNT is None or account is None or Path(account).resolve()!=CONSUMABLE_DISPLAY_ACCOUNT:raise ValueError('Uncertified injury/misc consumable wire contract')
        # Explicit cardsubtypeid is parsed at01028fc0/key4c. It bypasses the
        # itemType fallback01030a0c; class6/9 dispatch01028864 enriches supplied
        # healing/misc resources. No guessed itemType or effect field is sent.
        value={'id':item.instance_id,'resourceId':item.resource_id,'cardsubtypeid':ref['cardsubtype'],'lastSalePrice':0}
    else:value={'id':item.instance_id,'resourceId':item.resource_id,'itemType':'training',
        'cardsubtypeid':ref['cardsubtype'],'lastSalePrice':0}
    from .native_quick_sell_protocol import project_item
    return project_item(value,item,account)
def encode_item(item,catalog,card_display=False,account=None):
    ref=catalog.get(item.resource_id)
    value={'id':item.instance_id,'resourceId':item.resource_id,
            'cardsubtypeid':ref.card_subtype_id,'lastSalePrice':0,'teamid':ref.team_id}
    # Offline condition is fixed99, including missing/legacy lower stored values.
    # Do not rewrite account archives or the original engine's match report.
    from .player_condition_policy import player_condition
    value.update(player_condition())
    if item.training_resource_id is not None:value['training']=item.training_resource_id
    if item.injury_type is not None:
        value.update(injuryType=item.injury_type,injuryGames=item.injury_games)
    if item.formation_id is not None:
        from .local_formations import FORMATIONS
        value['formation']=FORMATIONS[item.formation_id]
    if item.special_version_id is not None:
        from .reconstructed_specials import version
        special=version(item.special_version_id)
        if special.base_resource_id!=item.resource_id:raise ValueError('Special/base identity mismatch')
        value.update(rating=special.rating,preferredPosition=special.position,rareflag=special.rareflag,
            attributeList=[{'index':index,'value':stat} for index,stat in enumerate(special.attributes)])
    elif card_display:
        from .local_content_source import rating_for,position_for,rarity_for,attributes_for
        value['rating']=rating_for(item.resource_id)
        value['preferredPosition']=position_for(item.resource_id)
        if rarity_for(item.resource_id):value['rareflag']=rarity_for(item.resource_id)
        value['attributeList']=[{'index':index,'value':stat} for index,stat in enumerate(attributes_for(item.resource_id))]
    if item.preferred_position is not None:value['preferredPosition']=item.preferred_position
    from .item_history import fields as history_fields
    value.update(history_fields(account,item.instance_id))   # CLUB-005 PLAYER BIO Item Details
    from .native_quick_sell_protocol import project_item
    return project_item(value,item,account)
def response_for(method,target,headers,body,store,squad_by_id=False,card_display=False):
    from .squad_management import selected as management_selected
    from .local_squads import get as get_squad,active_record,by_native_id,wire_id
    import re
    by_id=re.fullmatch(r'/ut/game/fifaworldmobile/squad/(0|[1-9][0-9]*)',target)
    valid_by_id=bool(squad_by_id and by_id and (by_id[1]=='0' or management_selected(store)))
    if (method!='GET' or not (target in (PURCHASED,SQUAD) or valid_by_id) or body or
        headers.get(b'host')!=b'10.0.2.2:18081' or headers.get(b'x-ut-sid')!=SID.encode() or
        headers.get(b'content-length',b'0')!=b'0'):return None
    persona=load_profile().persona_id;state=store.load(persona)
    record=(by_native_id(state,int(by_id[1])) if management_selected(store) else get_squad(state,int(by_id[1]))) if valid_by_id else active_record(state)
    if record is None:return None
    items={i.instance_id:i for i in state.owned_items}
    if target==PURCHASED:
        values=[encode_item(i,store.catalog,card_display,store.path.parent) for i in state.owned_items if item_pile(state,i.instance_id)=='unassigned']
        values += [i for i in encode_actives(state) if item_pile(state,i['id'])=='unassigned']
        values += [encode_consumable(i,store.path.parent) for i in state.owned_consumables if item_pile(state,i.instance_id)=='unassigned']
        values += [encode_owned_club_item(i,store.path.parent) for i in state.owned_club_items if item_pile(state,i.instance_id)=='unassigned']
        if state.active_manager is not None and item_pile(state,state.active_manager.instance_id)=='unassigned':
            values.append(encode_manager(state.active_manager))
        values += [encode_manager(m) for m in state.owned_managers if item_pile(state,m.instance_id)=='unassigned']
        result={'itemData':values}
        duplicates=[]
        for item in state.owned_items:
            if item_pile(state,item.instance_id)!='unassigned':continue
            from .reconstructed_specials import player_version_key
            existing=[i.instance_id for i in state.owned_items if player_version_key(i)==player_version_key(item) and
                      i.instance_id!=item.instance_id and item_pile(state,i.instance_id)=='club']
            if existing:duplicates.append({'itemId':item.instance_id,'duplicateItemId':min(existing)})
        # Duplicate club resources retain independent ownership identities.
        club_items=list(state.owned_club_items)+list(state.active_club_items)
        if state.active_badge is not None:
            from .local_football import OwnedClubItem
            club_items.append(OwnedClubItem(state.active_badge.instance_id,state.active_badge.resource_id,'badge'))
        for item in state.owned_club_items:
            if item_pile(state,item.instance_id)!='unassigned':continue
            existing=[i.instance_id for i in club_items if i.instance_id!=item.instance_id and
                (i.item_type,i.resource_id)==(item.item_type,item.resource_id) and item_pile(state,i.instance_id)=='club']
            if existing:duplicates.append({'itemId':item.instance_id,'duplicateItemId':min(existing)})
        if duplicates:result['duplicateItemIdList']=duplicates
        return json_response(result)
    slots={s.index:s.instance_id for s in record.lineup}
    indices=range(23) if management_selected(store) else sorted(slots)
    # The stock cache reuses its23references. Omitting an empty slot retains
    # the preceding team's handle; id0 is the recovered explicit null sentinel
    # (01028fc0 refuses ownership registration, 00b6e388 installs empty slots).
    value={'personaId':persona,'players':[
        {'index':index,'itemData':encode_item(items[slots[index]],store.catalog,card_display,store.path.parent)
         if index in slots else {'id':0}} for index in indices]}
    if record.id or management_selected(store):value['id']=wire_id(record) if management_selected(store) else record.id
    if record.name or management_selected(store):value['squadName']=record.name
    if record.summary is not None:
        summary=record.summary
        value.update(chemistry=summary.chemistry,rating=summary.rating,starRating=summary.star_rating)
    elif management_selected(store):value.update(chemistry=0,rating=0,starRating=0)
    if record.formation_id is not None:
        from .local_formations import FORMATIONS
        value['formation']=FORMATIONS[record.formation_id]
    elif management_selected(store):
        from .local_formations import FORMATIONS
        value['formation']=FORMATIONS[23]  # Recovered original engine fallback.
    if encode_actives(state):value['actives']=encode_actives(state)
    managers=([state.active_manager] if state.active_manager is not None else [])+list(state.owned_managers)
    chosen=next((m for m in managers if m.instance_id==record.manager_id),None)
    if record.manager_id and chosen is not None:value['manager']=[encode_manager(chosen)]
    elif management_selected(store):value['manager']=[{'id':0}]
    return json_response(value)
