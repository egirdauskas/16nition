"""Captured empty-target voucher Redeem; explicit resource opt-ins only.

Supplied Gold/Silver vouchers grant the corresponding supported v5 pack when
explicitly enabled. This is local integration policy; supplied amounts3020/3010
are not promoted to recovered EA product IDs.
The existing account prepared-image/CAS mechanism joins source retirement and
unopened ownership. No purchase receipt, wallet change or fixture is invented.
"""
from contextlib import contextmanager
import copy
import fcntl
import json
from pathlib import Path
import uuid

from .account_transaction import account_locked, atomic, recover_images
from .native_free_coins import encode, digest
from .local_football import FootballStore, owned_instance_ids, item_pile
from .local_content import ContentCatalog
from .local_packs import PackStore

DEFINITION = 'revival_gold_mixed_specials_v5'
RESOURCE = 5004015
VERSION = 'free_gold_voucher_v1'
FIRST, SLOTS = 62000, 64
SILVER_RESOURCE = 5004014
SILVER_DEFINITION = 'revival_silver_mixed_specials_v5'
BRONZE_RESOURCE = 5004013
BRONZE_DEFINITION = 'revival_bronze_mixed_specials_v5'
# Local caption namespaces, not EA product IDs or the supplied voucher amount.
RULES = {RESOURCE: (DEFINITION, VERSION, FIRST),
         SILVER_RESOURCE: (SILVER_DEFINITION, 'free_silver_voucher_v1', 62100),
         BRONZE_RESOURCE: (BRONZE_DEFINITION, 'free_bronze_voucher_v1', 62200)}
ACCOUNT = None
SILVER_ENABLED = False
BRONZE_ENABLED = False


def validate_grants(value):
    records = value.get('voucher_grants', [])
    if type(records) is not list or len(records) > SLOTS:
        raise ValueError('Invalid voucher grant capacity')
    owned = {r['catalog_id']: r for r in value['entitlements']+value['consumed']}
    sources, catalogs, owners = set(), set(), set()
    for ordinal, r in enumerate(records):
        if type(r) is not dict or set(r) != {'reward_id','source_id','resource_id','account_id',
                'persona_id','policy_version','entitlement','wire_id'}:
            raise ValueError('Invalid voucher receipt fields')
        source = r['source_id']
        if type(source) is not int or not 0 < source <= 0x7fffffffffffffff or source in sources:
            raise ValueError('Invalid/duplicate voucher source')
        namespace = uuid.UUID(r['account_id'])
        rule = RULES.get(r['resource_id']) if type(r['resource_id']) is int else None
        e = r['entitlement']
        restricted = type(e) is dict and e.get('untradeable') is True
        if (rule is None or
            type(r['persona_id']) is not int or r['persona_id'] != value['persona_id'] or
            r['policy_version'] != rule[1]+('_untradeable_v1' if restricted else '') or type(r['wire_id']) is not int or
            r['wire_id'] != rule[2]+ordinal or
            r['reward_id'] != str(uuid.uuid5(namespace, 'free-pack:'+str(source)))):
            raise ValueError('Invalid voucher source/policy identity')
        if (type(e) is not dict or set(e) != {'catalog_id','definition','provenance'}|({'untradeable'} if restricted else set()) or
            e['definition'] != rule[0] or e['provenance'] != 'revival_policy' or
            e['catalog_id'] in catalogs or e['catalog_id'] not in owned or
            any(owned[e['catalog_id']].get(k) != v for k,v in e.items())):
            raise ValueError('Voucher entitlement missing/conflicting')
        sources.add(source); catalogs.add(e['catalog_id']); owners.add(r['account_id'])
    if len(owners) > 1:
        raise ValueError('Foreign voucher account')
    return records


def aliases(store, value, journal=None, *, reserve=False):
    records = validate_grants(value)
    if not records and not reserve and ACCOUNT != store.path.parent.resolve():
        return {}
    namespace = {wire for _, _, first in RULES.values() for wire in range(first, first+SLOTS)}
    owned = {r['catalog_id'] for r in value['entitlements']+value['consumed']}
    from . import native_pack_sessions as sessions
    if owned & namespace and not sessions.selected(store.path.parent):
        raise ValueError('Ownership collides with voucher captions')
    from .local_store import active_offers
    products = store.path.with_name('products.json')
    if products.exists() and {r['product_id'] for r in active_offers(products,journal)} & namespace:
        raise ValueError('Store offer collides with voucher captions')
    if journal is None and store.path.with_name('purchases.json').exists():
        journal = json.loads(store.path.with_name('purchases.json').read_bytes())
    for r in (journal or {}).get('receipts', [])+([journal['prepared']] if journal and journal.get('prepared') else []):
        if {r[k] for k in ('product_id','next_product_id','sku_id') if k in r} & namespace:
            raise ValueError('Purchase collides with voucher captions')
    return {r['entitlement']['catalog_id']:r['wire_id'] for r in records}


def descriptions(store,*,value=None):
    if ACCOUNT != store.path.parent.resolve():
        return []
    aliases(store,store.load() if value is None else value,reserve=True)
    resources = (RESOURCE, SILVER_RESOURCE) if SILVER_ENABLED else (RESOURCE,)
    if BRONZE_ENABLED:resources+=(BRONZE_RESOURCE,)
    return [(wire, RULES[resource][0]) for resource in resources
            for wire in range(RULES[resource][2], RULES[resource][2]+SLOTS)]


def configure(account=None, *, silver=False, bronze=False):
    global ACCOUNT, SILVER_ENABLED, BRONZE_ENABLED
    ACCOUNT = None
    SILVER_ENABLED = False
    BRONZE_ENABLED = False
    if account is not None:
        c = FreePacksCoordinator(account,enabled=True,silver=silver,bronze=bronze)
        aliases(c.packs,c.packs.load(),reserve=True)
        ACCOUNT = c.account
        SILVER_ENABLED = silver
        BRONZE_ENABLED = bronze
        return c


class FreePacksCoordinator:
    def __init__(self, account, *, enabled=False, silver=False, bronze=False, fault=None):
        if enabled is not True:
            raise ValueError('Free pack redemption disabled by default')
        if type(silver) is not bool or type(bronze) is not bool:
            raise ValueError('Explicit Silver/Bronze voucher selectors required')
        self.silver = silver
        self.bronze = bronze
        from .store_release import projection_account
        self.account = Path(account).resolve()
        projection_account([self.account/n for n in ('profile.json','football.json','content.json',
                          'packs.json','seasons.json','definition.json','control.json')])
        self.path = self.account/'free-packs.json'
        if self.path.is_symlink() or (self.path.exists() and self.path.stat().st_nlink != 1):
            raise ValueError('Voucher journal alias refused')
        self.packs = PackStore(self.account/'packs.json')
        from .local_profile import ProfileStore
        self.profile = ProfileStore(self.account/'profile.json')
        self.football = FootballStore(self.account/'football.json',ContentCatalog(self.account/'content.json'))
        self.fault = fault

    def identity(self):
        p = self.profile.load()
        return {'identity_pid':p.identity_pid,'persona_id':p.persona_id,'user_id':p.user_id}

    @contextmanager
    def locked(self):
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
            try:
                with self.packs.transaction(),self.profile.transaction(),self.football.transaction():
                    yield
            finally:
                fcntl.flock(lock.fileno(),fcntl.LOCK_UN)

    def _empty(self):
        return {'schema':1,'account_id':str(uuid.uuid5(uuid.NAMESPACE_URL,str(self.account))),
                'account_identity':self.identity(),'receipts':[],'prepared':None}

    def _validate(self, value):
        if (type(value) is not dict or set(value) != {'schema','account_id','account_identity','receipts','prepared'} or
            type(value['schema']) is not int or value['schema'] != 1 or value['account_identity'] != self.identity() or
            type(value['receipts']) is not list):
            raise ValueError('Invalid voucher journal/account')
        uuid.UUID(value['account_id']); seen = set()
        for r in value['receipts']:
            if type(r) is not dict or set(r) != {'grant','packs_before_sha256','packs_after_sha256',
                    'football_before_sha256','football_after_sha256'}:
                raise ValueError('Invalid voucher journal receipt')
            g = r['grant']
            # Validate all receipt ordinals together below; do not reassign IDs.
            if g['source_id'] in seen or g['account_id'] != value['account_id']:
                raise ValueError('Duplicate/foreign voucher journal source')
            seen.add(g['source_id'])
            for k,h in r.items():
                if k != 'grant' and (type(h) is not str or len(h) != 64 or any(c not in '0123456789abcdef' for c in h)):
                    raise ValueError('Invalid voucher image digest')
        grants = [r['grant'] for r in value['receipts']]
        validate_grants({'persona_id':1,'entitlements':[g['entitlement'] for g in grants],
                         'consumed':[],'voucher_grants':grants})
        if value['prepared'] is not None:
            p = value['prepared']
            if type(p) is not dict or set(p) != {'transaction_id','images','state_after'}:
                raise ValueError('Invalid voucher intent')
            uuid.UUID(p['transaction_id']); final = p['state_after']
            if final.get('prepared') is not None:
                raise ValueError('Nested voucher intent')
            self._validate(final)
            if (any(final[k] != value[k] for k in ('schema','account_id','account_identity')) or
                final['receipts'][:-1] != value['receipts'] or len(final['receipts']) != len(value['receipts'])+1):
                raise ValueError('Voucher intent rewrites history')
            images = p['images']; receipt = final['receipts'][-1]
            if (type(images) is not list or len(images) != 2 or [i.get('name') for i in images] != ['packs.json','football.json'] or
                any(set(i) != {'name','before','after'} for i in images)):
                raise ValueError('Invalid voucher image targets')
            for image in images:
                for d in ('before','after'):
                    if digest(bytes.fromhex(image[d])) != receipt[image['name'].split('.')[0]+'_'+d+'_sha256']:
                        raise ValueError('Voucher image digest mismatch')
            packs,football = [json.loads(bytes.fromhex(i['before'])) for i in images]
            grant,after_packs,after_football = self._transition(value,packs,football,receipt['grant']['source_id'])
            if grant != receipt['grant'] or [after_packs,after_football] != [json.loads(bytes.fromhex(i['after'])) for i in images]:
                raise ValueError('Voucher intent changes unrelated state')
        return value

    def _read(self):
        return self._validate(json.loads(self.path.read_bytes())) if self.path.exists() else self._empty()

    def inspect(self):
        """Validate a quiescent archive without repairs or writes."""
        value=self._read()
        if value['prepared'] is not None:raise ValueError('Recover pending FreePack redemption before backup')
        return self._assert_applied(value)

    def _transition(self,value,packs,football,source):
        if type(source) is not int or not 0 < source <= 0x7fffffffffffffff:
            raise ValueError('Full voucher identity required')
        f = self.football.decode(football,1)
        item = next((i for i in f.owned_consumables if i.instance_id == source),None)
        if (item is None or item.resource_id not in RULES or
                (item.resource_id == SILVER_RESOURCE and not self.silver) or
                (item.resource_id == BRONZE_RESOURCE and not self.bronze) or
                item_pile(f,source) != 'unassigned'):
            raise ValueError('Owned unassigned enabled Free Pack voucher required')
        definition, version, first = RULES[item.resource_id]
        from .local_consumables import inventory_reference
        if inventory_reference(item.resource_id)['cardsubtype'] != 233:
            raise ValueError('Supplied voucher binding changed')
        prior = validate_grants(packs)
        if prior != [r['grant'] for r in value['receipts']] or packs.get('prepared'):
            raise ValueError('Conflicting voucher history/pending opening')
        key = packs['next_catalog_id']
        from .local_packs import private_limit
        if type(key) is not int or not 30001 <= key <= private_limit(packs) or len(prior) >= SLOTS:
            raise ValueError('Voucher capacity exhausted')
        e = {'catalog_id':key,'definition':definition,'provenance':'revival_policy'}
        if source in f.untradeable_instance_ids:
            e['untradeable']=True
            version+='_untradeable_v1'
        g = {'reward_id':str(uuid.uuid5(uuid.UUID(value['account_id']),'free-pack:'+str(source))),
             'source_id':source,'resource_id':item.resource_id,'account_id':value['account_id'],
             'persona_id':1,'policy_version':version,'entitlement':e,'wire_id':first+len(prior)}
        p = copy.deepcopy(packs);p['next_catalog_id']=key+1;p['entitlements'].append(e)
        p.setdefault('voucher_grants',[]).append(g)
        aliases(self.packs,p,reserve=True)
        # Reuse all existing paid/source namespace and ownership safeguards.
        from .native_paid_pack_presentation import aliases as presentation
        presentation(self.packs,value=p)
        after = copy.deepcopy(football)
        after['owned_consumables']=[i for i in after['owned_consumables'] if i['instance_id'] != source]
        after['inventory_locations']=[i for i in after.get('inventory_locations',[]) if i['instance_id'] != source]
        after['retired_instance_ids']=sorted(after.get('retired_instance_ids',[])+[source])
        self.football.decode(after,1)
        return g,p,after

    def _assert_applied(self,value):
        f = self.football.load(1);p = self.packs.load()
        if validate_grants(p) != [r['grant'] for r in value['receipts']]:
            raise ValueError('Voucher ownership history differs')
        for r in value['receipts']:
            source = r['grant']['source_id']
            if source in owned_instance_ids(f) or source not in f.retired_instance_ids:
                raise ValueError('Voucher source reappeared/retirement lost')
        return value

    def _recover(self,value):
        if value['prepared'] is not None:
            p=value['prepared'];recover_images(self.account,p['images'],writer=atomic,fault=self.fault)
            value=p['state_after'];atomic(self.path,encode(value))
            if self.fault:self.fault('after_source_commit',0)
        return self._assert_applied(value)

    @account_locked
    def recover(self):
        with self.locked():return self._recover(self._read())

    def _preview(self,value,source):
        if type(source) is not int or not 0 < source <= 0x7fffffffffffffff:
            raise ValueError('Full voucher identity required')
        prior=next((r for r in value['receipts'] if r['grant']['source_id']==source),None)
        if prior:return prior,None
        for name in ('packs.json','purchases.json','native-seasons.json','free-coins.json','quick-sells.json'):
            path=self.account/name
            if path.exists() and json.loads(path.read_bytes()).get('prepared'):
                raise ValueError('Recover pending '+name+' before voucher redemption')
        images=[];values=[]
        for name in ('packs.json','football.json'):
            raw=(self.account/name).read_bytes();images.append({'name':name,'before':raw.hex()});values.append(json.loads(raw))
        g,p,f=self._transition(value,*values,source)
        receipt={'grant':g}
        for image,after in zip(images,(p,f)):
            raw=encode(after);image['after']=raw.hex()
            for d in ('before','after'):receipt[image['name'].split('.')[0]+'_'+d+'_sha256']=digest(bytes.fromhex(image[d]))
        return receipt,images

    @account_locked
    def preview(self,source):
        with self.locked():
            value=self._read()
            if value['prepared'] is not None:raise ValueError('Recover pending voucher intent before preview')
            self._assert_applied(value)
            return self._preview(value,source)[0]

    @account_locked
    def redeem(self,source):
        with self.locked():
            value=self._recover(self._read());receipt,images=self._preview(value,source)
            if images is None:return receipt
            final=copy.deepcopy(value);final['receipts'].append(receipt)
            intent=copy.deepcopy(value);intent['prepared']={'transaction_id':str(uuid.uuid4()),'images':images,'state_after':final}
            self._validate(intent);atomic(self.path,encode(intent))
            if self.fault:self.fault('after_intent',0)
            self._recover(intent)
            return receipt
