"""Revival Store offers: one currency debit -> entitlement, never contents.

The captured request has no transaction nonce. Each wire offer has one purchase
per persona and an immutable receipt. Repeatable policy SKUs rotate their wire
offer id after commit, retaining old ids as retry keys.
"""
import json, os, tempfile, fcntl
from dataclasses import replace
from pathlib import Path
from .account_transaction import account_locked
from .local_store import products,active_offers,next_offer_id
from .local_profile import ProfileStore, validate_credits
from .local_packs import PackStore, DEFINITIONS

# Keep established coin receipts byte/schema compatible. Points receipts record
# their own balance pair, never masquerading as credits or modifying coins.
BALANCES={'coins':('coin_price','credits','credits_before','credits_after'),
          'points':('point_price','fifa_points','points_before','points_after')}

def currency_fields(currency):
    if type(currency) is not str or currency not in BALANCES:raise ValueError('Unsupported purchase currency')
    return BALANCES[currency]

class PurchaseStore:
    def __init__(self, path, profile, packs, catalog=None):
        self.path=Path(path); self.profile=profile; self.packs=packs
        self.catalog=Path(catalog or self.path.with_name('products.json'))

    def load(self):
        if not self.path.exists():return {'persona_id':1,'receipts':[]}
        value=json.loads(self.path.read_text())
        if (set(value)-{'persona_id','receipts','prepared'} or
            not {'persona_id','receipts'}<=set(value) or type(value['persona_id']) is not int or
            value['persona_id']!=1 or type(value['receipts']) is not list):raise ValueError('Invalid purchase journal')
        from .local_packs import private_limit
        limit=65535;wide_limit=None
        ids=[]; entitlement_ids=[]
        for row in value['receipts']+([value['prepared']] if 'prepared' in value else []):
            if type(row) is not dict:raise ValueError('Invalid purchase receipt')
            _,_,before,after=currency_fields(row.get('currency'))
            required={'product_id','currency','amount',before,after,'entitlement'}
            if row.get('delivery','direct')!='direct':raise ValueError('Invalid purchase delivery')
            if (set(row)-{'session_id','delivery'} not in (required,required|{'sku_id','next_product_id'}) or
                type(row['product_id']) is not int or not (17000 if 'session_id' in row else 40001)<=row['product_id']<=65535):
                raise ValueError('Invalid purchase receipt')
            if 'sku_id' in row and (type(row['sku_id']) is not int or not 40001<=row['sku_id']<=65535 or
                type(row['next_product_id']) is not int or not row['product_id']<row['next_product_id']<=65535):
                raise ValueError('Invalid repeatable offer receipt')
            if 'session_id' in row and (type(row['session_id']) is not str or not row['session_id'].startswith('fifa16-pack-') or len(row['session_id'])!=44 or 'sku_id' not in row):raise ValueError('Invalid purchase session')
            for key in ('amount',before,after):validate_credits(row[key])
            if not row['amount'] or row[before]-row['amount']!=row[after]:raise ValueError('Invalid purchase debit')
            e=row['entitlement']
            if type(e) is dict and type(e.get('catalog_id')) is int and e['catalog_id']>65535:
                if wide_limit is None:wide_limit=private_limit(self.packs.load())
                limit=wide_limit
            if (type(e) is not dict or set(e)!={'catalog_id','definition','provenance'} or
                type(e['catalog_id']) is not int or not 30001<=e['catalog_id']<=limit or
                e['definition'] not in DEFINITIONS or e['provenance']!='revival_policy'):raise ValueError('Invalid purchase entitlement')
            ids.append((row.get('session_id'),row['product_id']))
            entitlement_ids.append(e['catalog_id'])
        if len(set(ids))!=len(ids):raise ValueError('Duplicate purchase receipt')
        if len(set(entitlement_ids))!=len(entitlement_ids):raise ValueError('Duplicate purchase entitlement')
        future=[(r.get('session_id'),r['next_product_id']) for r in value['receipts']+([value['prepared']] if 'prepared' in value else []) if 'next_product_id' in r]
        if len(set(future))!=len(future):raise ValueError('Duplicate offer reservation')
        last={}
        for row in value['receipts']+([value['prepared']] if 'prepared' in value else []):
            if 'sku_id' not in row or 'session_id' in row:continue
            sku=row['sku_id']
            if row['product_id']!=last.get(sku,sku):raise ValueError('Broken repeatable SKU chain')
            last[sku]=row['next_product_id']
        return value

    def _prior(self,value,key):
        from . import native_pack_sessions as sessions
        if sessions.selected(self.packs.path.parent):return sessions.prior_purchase(value,key)
        return next((r for r in value['receipts']+([value['prepared']] if value.get('prepared') else []) if r['product_id']==key and 'session_id' not in r),None)

    def save(self, value):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix=self.path.name+'.',dir=self.path.parent);tmp=Path(name)
        try:
            with os.fdopen(fd,'w') as out:
                out.write(json.dumps(value,indent=2,sort_keys=True)+'\n');out.flush();os.fsync(out.fileno())
            PurchaseStore(tmp,self.profile,self.packs,self.catalog).load()
            tmp.replace(self.path)
            fd=os.open(self.path.parent,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
        finally:
            if tmp.exists():tmp.unlink()

    @account_locked
    def preview(self, product_id, currency='coins'):
        price_field,balance_field,before,after=currency_fields(currency)
        if type(product_id) is not int:raise ValueError('Unsupported purchase')
        value=self.load()
        from . import native_pack_sessions as sessions
        if sessions.selected(self.packs.path.parent) and sessions.current() is None:raise ValueError('Native authentication required before purchase')
        if 'prepared' in value:raise ValueError('Recover prepared purchase before serving')
        prior=self._prior(value,product_id)
        if prior:
            if prior['currency']!=currency:raise ValueError('Purchase retry currency mismatch')
            from .native_paid_pack_presentation import validate_purchase
            validate_purchase(self.packs,prior,value)
            return prior
        product=next((r for r in active_offers(self.catalog,value) if r['product_id']==product_id),None)
        if product is None:raise ValueError('Unknown local product')
        if price_field not in product:raise ValueError('Product currency mismatch')
        profile=self.profile.load()
        if profile.persona_id!=1:raise ValueError('Foreign account')
        balance=getattr(profile,balance_field);price=product[price_field]
        if balance<price:raise ValueError('Insufficient '+currency)
        key=self.packs.load()['next_catalog_id']
        from .local_packs import private_limit
        if key>private_limit(self.packs.load()):raise ValueError('Entitlement allocator exhausted')
        receipt={'product_id':product_id,'currency':currency,'amount':price,
            before:balance,after:balance-price,
            'entitlement':{'catalog_id':key,'definition':product['definition'],'provenance':'revival_policy'}}
        if product.get('repeatable'):
            receipt.update(sku_id=product['sku_id'],next_product_id=next_offer_id(self.catalog,value,product['sku_id']))
        from .store_direct_delivery import applies as direct_delivery,DIRECT
        if direct_delivery(self.packs.path.parent,product['definition']):
            receipt['delivery']=DIRECT
        from . import native_pack_sessions as sessions
        if sessions.selected(self.packs.path.parent):receipt['session_id']=sessions.current()['sid']
        from .native_paid_pack_presentation import validate_purchase
        validate_purchase(self.packs,receipt,value)
        return receipt

    def _complete(self, value):
        receipt=value['prepared'];profile=self.profile.load();packs=self.packs.load()
        from .native_paid_pack_presentation import validate_purchase
        validate_purchase(self.packs,receipt,value)
        _,balance_field,before,after=currency_fields(receipt['currency'])
        balance=getattr(profile,balance_field)
        e=receipt['entitlement'];key=e['catalog_id']
        # Validate both sides before any new write. Unexpected concurrent edits
        # fail closed; recovery never silently overwrites another transaction.
        if balance not in (receipt[before],receipt[after]):raise ValueError('Purchase balance conflict')
        existing=next((r for r in packs['entitlements']+packs['consumed'] if r['catalog_id']==key),None)
        if existing is not None and any(existing[k]!=e[k] for k in e):raise ValueError('Purchase entitlement conflict')
        if existing is None and packs['next_catalog_id']!=key:raise ValueError('Purchase allocator conflict')
        if balance==receipt[before]:
            self.profile.save(replace(profile,**{balance_field:receipt[after]}))
        if existing is None:
            packs['entitlements'].append(e);packs['next_catalog_id']=key+1;self.packs.save(packs)
        value['receipts'].append(receipt);value.pop('prepared');self.save(value)
        return receipt

    @account_locked
    def _transaction(self, product_id=None, currency='coins'):
        currency_fields(currency)
        if product_id is not None and type(product_id) is not int:raise ValueError('Unsupported purchase')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.with_name(self.path.name+'.lock').open('a') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
            try:
                with self.packs.transaction(), self.profile.transaction():
                    value=self.load()
                    history=value['receipts']+([value['prepared']] if 'prepared' in value else [])
                    if product_id is not None and not any(p['product_id']==product_id for p in active_offers(self.catalog,value)) and self._prior(value,product_id) is None:
                        raise ValueError('Unknown local product')
                    # Reject a wrong-currency request before recovery can write
                    # another committed transaction's prepared state.
                    if product_id is not None:
                        prior=self._prior(value,product_id)
                        if prior is not None and prior['currency']!=currency:raise ValueError('Purchase retry currency mismatch')
                        product=next((p for p in active_offers(self.catalog,value) if p['product_id']==product_id),None)
                        if prior is None and currency_fields(currency)[0] not in product:raise ValueError('Product currency mismatch')
                    if 'prepared' in value:self._complete(value)
                    if product_id is None:return None
                    receipt=self.preview(product_id,currency)
                    if self._prior(value,product_id) is not None:return receipt
                    value['prepared']=receipt;self.save(value)
                    return self._complete(value)
            finally:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)

    def purchase(self,product_id,currency='coins'):return self._transaction(product_id,currency)
    def recover(self):return self._transaction()

def configured_store(packs):
    return PurchaseStore(packs.path.with_name('purchases.json'),ProfileStore(),packs)
