"""Captured catalog45/PurchasePack43: opening and limited coins/points."""
import json
from .pack_catalog_control import PATH
from .game_auth import SID
from .identity import json_response
from .local_packs import catalog_response,receipt_items
OPEN='/ut/game/fifaworldmobile/purchased/items'
def recover_transactions(store,football=None):
    """Finish existing authorized intents before serving later account work.

    Reuse the startup order and existing ownership/purchase journals. This does
    not create an entitlement or debit without a previously prepared operation.
    """
    if football is not None:store.recover(football)
    elif store.load().get('prepared'):raise ValueError('Pack recovery needs its football store')
    if store.path.with_name('products.json').exists():
        from .local_purchase import configured_store
        configured_store(store).recover()
        if football is not None:
            recover_direct_deliveries(store,football)

def recover_direct_deliveries(store,football):
    """Finish a committed direct purchase whose opening was interrupted."""
    from .local_purchase import configured_store
    from .store_direct_delivery import commit,is_direct
    unopened={e['catalog_id'] for e in store.load()['entitlements']}
    for receipt in configured_store(store).load()['receipts']:
        if is_direct(receipt) and receipt['entitlement']['catalog_id'] in unopened:
            commit(store,football,receipt)

def purchase_request(method,target,headers,body):
    if (method!='POST' or target!=OPEN or headers.get(b'host')!=b'10.0.2.2:18081' or
        headers.get(b'x-ut-sid')!=SID.encode() or headers.get(b'content-type')!=b'application/json' or
        headers.get(b'content-length')!=str(len(body)).encode()):return None
    from . import native_pack_sessions as sessions
    minimum=17000 if sessions.selected(sessions.ACCOUNT) else 40001
    try:
        value=json.loads(body)
        if (type(value) is not dict or set(value)!={'packId','useCredits','usePreOrder','currency'} or
            type(value['packId']) is not int or not minimum<=value['packId']<=65535 or
            type(value['useCredits']) is not int or
            type(value['usePreOrder']) is not int or value['usePreOrder']!=0):return None
        if value['currency']=='COINS' and value['useCredits']==1:return value['packId'],'coins'
        # Run332 actual FP body: useCredits0/usePreOrder0/currencyPOINTS.
        if value['currency']=='POINTS' and value['useCredits']==0:return value['packId'],'points'
        return None
    except (ValueError,TypeError,UnicodeError):return None

def purchase_key(method,target,headers,body):
    """Compatibility accessor for the established coin-only callers/tests."""
    request=purchase_request(method,target,headers,body)
    return request[0] if request is not None and request[1]=='coins' else None

def encode_purchase(receipt):
    # Explicit revival policy: purchase grants entitlement; method4 opens later.
    # Shared 022f69c4 accepts an empty vector; UnassignedItems guards zero cards.
    return json_response({'numberItems':0,'purchasedPackId':receipt['product_id'],'itemList':[]})

def encode_paid_reply(receipt,store,football,*,preview=False):
    """Wrapper purchases return the entitlement reply; direct ones the cards.

    Direct delivery reuses the opening reply shape with the purchased wire
    offer as purchasedPackId (stock StoreCommonModel goes to Unassigned).
    """
    if receipt.get('delivery')!='direct':
        return encode_purchase(receipt)
    if football is None:
        raise ValueError('Direct delivery requires the football inventory')
    from . import store_direct_delivery as direct
    opened=direct.preview(store,football,receipt) if preview else direct.completed(store,receipt)
    return encode_open(opened,football,receipt['product_id'])

def open_key(method,target,headers,body,*,allow_reserved=False):
    if (method!='POST' or target!=OPEN or headers.get(b'host')!=b'10.0.2.2:18081' or
        headers.get(b'x-ut-sid')!=SID.encode() or headers.get(b'content-type')!=b'application/json' or
        headers.get(b'content-length')!=str(len(body)).encode()):return None
    try:
        value=json.loads(body)
        if (type(value) is not dict or set(value)!={'packId','useCredits','usePreOrder'} or
            type(value['packId']) is not int or not (1 if allow_reserved else 30001)<=value['packId']<=65535 or
            type(value['useCredits']) is not int or value['useCredits']!=0 or
            type(value['usePreOrder']) is not int or value['usePreOrder']!=1):return None
        return value['packId']
    except (ValueError,TypeError,UnicodeError):return None
def encode_open(receipt,football,wire_id=None):
    from .local_football import OwnedConsumableItem,OwnedClubItem
    from .football_protocol import encode_item,encode_consumable,encode_owned_club_item
    # Receipt freezes the allocation; owned mutable condition/preferences are
    # authoritative if a retry follows a legitimate later player mutation.
    state=football.load(1)
    current={i.instance_id:i for i in state.owned_items+state.owned_consumables+state.owned_club_items}
    items=[]
    for allocated in receipt_items(receipt):
        item=current.get(allocated.instance_id,allocated)
        if item.resource_id!=allocated.resource_id:raise ValueError('Receipt resource identity changed')
        if type(item) is not type(allocated) or getattr(item,'special_version_id',None)!=getattr(allocated,'special_version_id',None):
            raise ValueError('Receipt owned version identity changed')
        items.append(encode_owned_club_item(item,football.path.parent) if type(item) is OwnedClubItem else
            encode_consumable(item,football.path.parent) if type(item) is OwnedConsumableItem else encode_item(item,football.catalog,True,football.path.parent))
        # Preview is encoded before the journal commits ownership. The pinned
        # entitlement must therefore carry its restriction on the first reply,
        # as well as later ordinary inventory refreshes.
        if receipt.get('untradeable') is True:items[-1].update(untradeable=True,discardValue=0)
    return json_response({'numberItems':len(items),'purchasedPackId':receipt['catalog_id'] if wire_id is None else wire_id,'itemList':items})
def response_for(method,target,headers,body,store,football=None):
    from . import native_pack_sessions as sessions
    if sessions.is_stale(headers):return sessions.stale_reply(method,target,headers,body,store,football)
    from .native_source_pack_presentation import enabled as source_presentation
    paid=purchase_request(method,target,headers,body)
    if paid is not None and store.path.with_name('products.json').exists():
        from .local_purchase import configured_store
        try:
            receipt=configured_store(store).preview(*paid)
            return encode_paid_reply(receipt,store,football,preview=True)
        except ValueError:return None
    if (method=='GET' and target=='/fut/packs/loc/android/StorePackDescriptions.en_us.xml' and not body
        and headers.get(b'host')==b'10.0.2.2:18081'
        and (store.path.with_name('products.json').exists() or source_presentation(store)
             or not store.load()['entitlements'])):
        # 022f4748 accepts well-formed XML with no trans-unit entries.
        # No recovered historic product translation or art is claimed.
        from .local_packs import pack_descriptions
        payload=pack_descriptions(store)
        return (b'HTTP/1.1 200 OK\r\nContent-Type: application/xml\r\nConnection: close\r\nContent-Length: '
                +str(len(payload)).encode()+b'\r\n\r\n'+payload)
    if football is not None:
        from .reward_capacity import allows_low_open
        key=open_key(method,target,headers,body,allow_reserved=allows_low_open(store.path.parent))
        if key is not None:
            from .native_paid_pack_presentation import resolve_open
            try:
                from . import native_pack_sessions as sessions
                ident=sessions.opening_identity(key) if sessions.selected(store.path.parent) else None
                return encode_open(store.preview(resolve_open(store,key),football,ident),football,key)
            except ValueError:return None
    if (method!='GET' or target!=PATH or body or headers.get(b'host')!=b'10.0.2.2:18081' or
        headers.get(b'x-ut-sid')!=SID.encode() or headers.get(b'content-length',b'0')!=b'0'):
        return None
    # Content, artwork and aliases project one validated ownership snapshot;
    # do not redraw old opening receipts separately for the same response.
    pack_state=store.load()
    value=catalog_response(store,pack_state)
    from .local_store import catalog_rows
    value['purchase']+=catalog_rows(store.path.with_name('products.json'))
    from .store_demo_offers import envelope_fields
    value.update(envelope_fields(store.path.with_name('products.json')))
    from .native_pack_art import project
    value=project(value,store,pack_state=pack_state)
    from .native_paid_pack_presentation import project as present
    value=present(value,store,pack_state=pack_state)
    return json_response(value)
def commit_request(method,target,headers,body,store,football):
    from . import native_pack_sessions as sessions
    if sessions.is_stale(headers):return sessions.stale_reply(method,target,headers,body,store,football)
    paid=purchase_request(method,target,headers,body)
    if paid is not None and store.path.with_name('products.json').exists():
        from .local_purchase import configured_store
        receipt=configured_store(store).purchase(*paid)
        if receipt.get('delivery')=='direct':
            from .store_direct_delivery import commit
            commit(store,football,receipt)
        return encode_paid_reply(receipt,store,football)
    from .reward_capacity import allows_low_open
    key=open_key(method,target,headers,body,allow_reserved=allows_low_open(store.path.parent))
    if key is None:return None
    from .native_paid_pack_presentation import resolve_open
    from . import native_pack_sessions as sessions
    ident=sessions.opening_identity(key) if sessions.selected(store.path.parent) else None
    return encode_open(store.open(resolve_open(store,key),football,ident),football,key)
