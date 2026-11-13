"""Pure isolated Buy Now ownership/wallet plan; no endpoint or account writes.

The existing recoverable image journal pattern will commit plans only after
listing custody/ownership, native request identity and policy are established.
Fees/limits in this module are explicitly TEST FIXTURE inputs, never revived or
historical product defaults. Production policy is intentionally unconfigured.
"""
from dataclasses import asdict,replace
import hashlib,json,uuid
from pathlib import Path
from .account_transaction import account_locked
from .local_profile import ProfileStore,validate_credits
from .local_football import FootballStore,owned_instance_ids,validate as validate_football
from .local_content import ContentCatalog
ROOT=Path(__file__).resolve().parents[1]

def encode(value):return (json.dumps(value,indent=2,sort_keys=True)+'\n').encode()
def digest(value):return hashlib.sha256(value).hexdigest()

def test_policy(value):
    if (type(value) is not dict or set(value)!={'classification','version','fee_basis_points','minimum_price','maximum_price'} or
        value['classification']!='backend_test_fixture' or value['version']!='market_plan_test_v1'):
        raise ValueError('Market policy unconfigured; explicit isolated test fixture required')
    for name in ('fee_basis_points','minimum_price','maximum_price'):
        if type(value[name]) is not int:raise ValueError('Integer test price/fee limits required')
    if not 0<=value['fee_basis_points']<=10000 or not 0<value['minimum_price']<=value['maximum_price']<=0x7fffffff:
        raise ValueError('Invalid bounded test policy')
    return value

def account_view(path):
    original=Path(path);path=original.resolve()
    if (original.is_symlink() or ROOT/'reports' not in path.parents or path.name!='isolated-account' or
        not (path/'.lab-snapshot.json').is_file()):raise ValueError('Archived isolated account required')
    for file in path.glob('*.json'):
        if file.is_symlink():raise ValueError('Account alias refused')
        real=ROOT/'server/data/development/fm16in2026'/file.name
        if real.exists() and file.samefile(real):raise ValueError('Real account alias refused')
    before={name:(path/name).read_bytes() for name in ('profile.json','football.json')}
    profile=ProfileStore(path/'profile.json').load();store=FootballStore(path/'football.json',ContentCatalog(path/'content.json'));football=store.load(profile.persona_id)
    if before!={name:(path/name).read_bytes() for name in before}:raise ValueError('Account changed during plan read')
    for name in ('packs.json','purchases.json','native-seasons.json'):
        file=path/name
        if file.exists():
            value=json.loads(file.read_text())
            pending=(value.get('prepared') is not None if name=='native-seasons.json' else 'prepared' in value)
            if pending or value.get('active_match') is not None:raise ValueError('Pending account operation; recover before market plan')
    return path,before,profile,football,store

def identity(profile):return {'identity_pid':profile.identity_pid,'persona_id':profile.persona_id,'user_id':profile.user_id}

@account_locked
def buy_now_plan(seller,buyer,instance_id,listing_id,price,*,policy=None):
    rule=test_policy(policy);validate_credits(price)
    if not rule['minimum_price']<=price<=rule['maximum_price']:raise ValueError('Test price outside configured limits')
    if type(instance_id) is not int or not 0<instance_id<=0x7fffffffffffffff:raise ValueError('Invalid owned instance')
    listing=str(uuid.UUID(listing_id))
    seller,sbefore,sp,sf,sstore=account_view(seller);buyer,bbefore,bp,bf,bstore=account_view(buyer)
    if seller==buyer or identity(sp)==identity(bp) or sp.identity_pid==bp.identity_pid or sp.user_id==bp.user_id:
        raise ValueError('Independent account ownership required; self trade refused')
    if instance_id in owned_instance_ids(bf):raise ValueError('Buyer already owns this instance')
    if instance_id in {s.instance_id for s in sf.active_lineup}:raise ValueError('Cannot sell active squad membership')
    if instance_id in set(sf.retired_instance_ids)|set(bf.retired_instance_ids):raise ValueError('Retired identity cannot be traded')
    item=next((i for i in sf.owned_items+sf.owned_consumables if i.instance_id==instance_id),None)
    if item is None:raise ValueError('Seller does not own supported player/consumable')
    from .local_football import OwnedPlayerItem,ItemLocation
    player=isinstance(item,OwnedPlayerItem)
    if player:
        from .card_pool import card_index
        card=card_index().get(item.resource_id)
        if card is None or not card.lookup_supported:raise ValueError('Player resource lacks supplied lookup support')
    if any(r.target_instance_id==instance_id for r in sf.consumable_applications):
        raise ValueError('Applied-item audit ownership requires a proven transfer/custody contract')
    if bp.credits<price:raise ValueError('Insufficient buyer coins')
    fee=price*rule['fee_basis_points']//10000;proceeds=price-fee
    seller_credits=validate_credits(sp.credits+proceeds);buyer_credits=validate_credits(bp.credits-price)
    removed=replace(sf,owned_items=tuple(i for i in sf.owned_items if i.instance_id!=instance_id),
        owned_consumables=tuple(i for i in sf.owned_consumables if i.instance_id!=instance_id),
        inventory_locations=tuple(i for i in sf.inventory_locations if i.instance_id!=instance_id))
    added=replace(bf,owned_items=bf.owned_items+((item,) if player else ()),
        owned_consumables=bf.owned_consumables+(() if player else (item,)),
        inventory_locations=bf.inventory_locations+(ItemLocation(instance_id,'unassigned'),),
        next_instance_id=max(bf.next_instance_id or max(owned_instance_ids(bf),default=0)+1,instance_id+1))
    # Transfer removes custody without marking permanent discard. A future
    # listing escrow/cancel path must retain the same distinction explicitly.
    validate_football(removed,sstore.catalog);validate_football(added,bstore.catalog)
    sprofile=json.loads(sbefore['profile.json']);sprofile['credits']=seller_credits
    bprofile=json.loads(bbefore['profile.json']);bprofile['credits']=buyer_credits
    images=[]
    for folder,raw,new in [(seller,sbefore,{'profile.json':sprofile,'football.json':asdict(removed)}),
                           (buyer,bbefore,{'profile.json':bprofile,'football.json':asdict(added)})]:
        for name in ('profile.json','football.json'):
            target=encode(new[name]);images.append({'account_path':str(folder),'name':name,
                'before_sha256':digest(raw[name]),'after_sha256':digest(target),
                'before_hex':raw[name].hex(),'after_hex':target.hex()})
    if sbefore!={n:(seller/n).read_bytes() for n in sbefore} or bbefore!={n:(buyer/n).read_bytes() for n in bbefore}:
        raise ValueError('Account changed while building plan')
    return {'classification':'backend_only_uncommitted_plan','policy_version':rule['version'],
            'settlement_id':str(uuid.uuid5(uuid.UUID(listing),'market-settlement')),'listing_id':listing,
            'seller':identity(sp),'buyer':identity(bp),'instance_id':instance_id,'resource_id':item.resource_id,
            'price':price,'fee':fee,'seller_proceeds':proceeds,'currency':'coins','images':images,
            'commit_enabled':False,'missing_authority':['persistent listing custody/winner state','genuine stock request/retry identity','approved fees/price limits','existing journal commit integration']}
