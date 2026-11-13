"""Prospective paid-offer presentation; ownership journals stay intact.

00b71150 binds original XML captions by the catalog ID. A bought offer already
has a descriptor; a newly allocated internal entitlement does not. Reuse that
unique retired wire offer for display/open routing, never for ownership identity.
Explicit v2/v3 selectors reserve typed successor captions at normal startup;
v1 retains its original behavior. v4 admits a separately backed-up, explicitly
deployed real Store. New policy versions use distinct namespaces.
"""
import hashlib,json
from pathlib import Path
ACCOUNT=None
POLICY=None
MARKER='native-paid-pack-presentation.json'
FRESH_VERSION='native_paid_pack_presentation_fresh_v1'

def configure(account=None):
 global ACCOUNT,POLICY
 ACCOUNT=POLICY=None
 if account is None:return
 from . import native_source_pack_presentation as source
 if source.ACCOUNT is not None:raise ValueError('Paid/source presentation selectors are exclusive')
 from .store_release import projection_account, selected, validate as validate_release
 account=Path(account).resolve()
 from . import fresh_account_runtime as fresh
 from . import native_pack_sessions as sessions
 fresh_selected=fresh.selected(account)
 validated=projection_account([account/n for n in ('profile.json','football.json','content.json','packs.json','seasons.json','definition.json','control.json')])
 if fresh_selected:
  configuration=fresh.validate(account)
  if not sessions.selected(account):
   raise ValueError('Fresh pack sessions must be selected first')
  if type(configuration.get('initial_catalog_id')) is not int or not 30001<=configuration['initial_catalog_id']<=65535:
   raise ValueError('Invalid fresh paid presentation cutoff')
  ACCOUNT=account
  POLICY={
   'version':FRESH_VERSION,'classification':'fresh_account_direct',
   'first_catalog_id':configuration['initial_catalog_id'],
   'fresh_marker_sha256':fresh.marker_sha(account),
  }
  return
 policy=json.loads((account/MARKER).read_text())
 base_keys={'version','classification','first_catalog_id','origin_archive'}
 from .native_paid_caption_reservations import VERSIONS, validate_origin, validate_current
 expected_keys=base_keys|{'caption_origin_archive','caption_bindings'} if policy.get('version') in VERSIONS else base_keys
 if (set(policy)!=expected_keys or
     policy['version'] not in ('native_paid_pack_presentation_v1',*VERSIONS) or policy['classification']!=('backed_up_local_store' if selected(account) else 'isolated_prospective_projection') or
     type(policy['first_catalog_id']) is not int or not 30001<=policy['first_catalog_id']<=65535):raise ValueError('Invalid paid presentation policy')
 origin=Path(policy['origin_archive']).resolve()
 if selected(account) and str(origin)!=validate_release(account)['origin_archive']:raise ValueError('Deployment origin differs')
 if (not selected(account) and origin.parent!=account.parent) or origin==account:raise ValueError('Separate same-lab origin archive required')
 manifest=json.loads((origin/'.lab-snapshot.json').read_text())['sha256']
 for name,sha in manifest.items():
  path=origin/name
  if Path(name).name!=name or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Paid presentation origin changed')
 if MARKER in manifest:raise ValueError('Origin must precede projection activation')
 if json.loads((origin/'packs.json').read_text())['next_catalog_id']!=policy['first_catalog_id']:raise ValueError('Projection must begin at the archived allocator')
 old=json.loads((origin/'purchases.json').read_text())
 if old.get('prepared') or any(r['entitlement']['catalog_id']>=policy['first_catalog_id'] for r in old['receipts']):raise ValueError('Quiescent prospective origin required')
 # Verify against live journals before installing the process-scoped selector.
 from .local_packs import PackStore
 from .local_purchase import PurchaseStore
 from .local_profile import ProfileStore
 store=PackStore(account/'packs.json')
 journal=PurchaseStore(account/'purchases.json',ProfileStore(account/'profile.json'),store).load()
 from .native_pack_sessions import legacy_state
 _aliases(legacy_state(store.load(),'packs'),legacy_state(journal,'purchases'),policy['first_catalog_id'],_currencies(policy),version=policy['version'])
 if policy['version'] in VERSIONS:
  validate_origin(account,policy)
  validate_current(account,policy,legacy_state(store.load(),'packs'),legacy_state(journal,'purchases'))
 ACCOUNT=account;POLICY={**policy,'marker_sha256':hashlib.sha256((account/MARKER).read_bytes()).hexdigest()}

def enabled(store):
 if ACCOUNT is None:return False
 if store.path.resolve().parent!=ACCOUNT:raise ValueError('Paid presentation account differs')
 if POLICY.get('version')==FRESH_VERSION:
  from . import fresh_account_runtime as fresh
  if not fresh.selected(ACCOUNT):
   return False
  if fresh.marker_sha(ACCOUNT) != POLICY['fresh_marker_sha256']:
   raise ValueError('Fresh paid presentation policy changed')
  return True
 from .store_release import selected,validate as validate_release
 if selected(ACCOUNT):validate_release(ACCOUNT)
 if hashlib.sha256((ACCOUNT/MARKER).read_bytes()).hexdigest()!=POLICY['marker_sha256']:raise ValueError('Paid presentation policy changed')
 return True

def _currencies(policy):
 from .native_paid_caption_reservations import VERSION_V5,VERSION_V6,VERSION_V7,VERSION_V8,VERSION_V9
 return ('coins','points') if policy['version'] in (VERSION_V5,VERSION_V6,VERSION_V7,VERSION_V8,VERSION_V9) else ('coins',)

def _aliases(value,journal,first,currencies=('coins',),*,version=None):
 from .classic_pack_store import SUPPORTED_V7,SUPPORTED_V8,SUPPORTED_V9,SUPPORTED_V10,SUPPORTED_V11
 owned={r['catalog_id']:r for r in value['entitlements']+value['consumed']}
 aliases={}
 allowed=None
 for receipt in journal['receipts']+([journal['prepared']] if journal.get('prepared') else []):
  e=receipt['entitlement'];key=e['catalog_id']
  if key<first:continue
  if allowed is None:
   allowed = set(SUPPORTED_V7.values())|set(SUPPORTED_V8.values())|set(SUPPORTED_V9.values())|set(SUPPORTED_V10.values())|set(SUPPORTED_V11.values())
   from .specialist_consumable_packs import policy as specialist_policy
   allowed.update(specialist_policy()['pack_definitions'])
   if version in ('native_paid_pack_presentation_v7','native_paid_pack_presentation_v8','native_paid_pack_presentation_v9'):
    from .club_item_packs import bindings
    allowed.update(bindings().values())
   if version in ('native_paid_pack_presentation_v8','native_paid_pack_presentation_v9'):
    from .standard_pack_specs import bindings,policy
    allowed.update(bindings().values());allowed.add(policy()['consumer']['definition'])
    from .store_pool_amendment import policy as amended
    allowed.update(r['definition'] for r in amended()['bindings'])
    if version=='native_paid_pack_presentation_v9':
     from .pack_family_split import DEFINITIONS as split_definitions
     allowed.update(split_definitions)
  if receipt['currency'] not in currencies or e['definition'] not in allowed:raise ValueError('Only approved coin packs can use paid presentation')
  wire=receipt['product_id']
  if wire in aliases.values() or (wire in owned and wire!=key):raise ValueError('Paid presentation namespace collision')
  if key in owned and any(owned[key].get(k)!=v for k,v in e.items()):raise ValueError('Paid presentation entitlement conflicts')
  if key not in owned and receipt in journal['receipts']:raise ValueError('Paid presentation ownership missing')
  aliases[key]=wire
 for key,wire in aliases.items():
  if key in aliases.values() and wire!=key:raise ValueError('Internal ID collides with another wire alias')
 return aliases

def aliases(store,value=None,journal=None):
 from . import native_pack_sessions as sessions
 if sessions.selected(store.path.parent):return sessions.mapping(pack_state=value,journal=journal)
 return legacy_aliases(store,value,journal)

def legacy_aliases(store,value=None,journal=None):
 from .native_free_packs import aliases as voucher_aliases
 from .native_pack_sessions import legacy_state
 current=legacy_state(store.load() if value is None else value,'packs')
 if enabled(store) and POLICY.get('version')==FRESH_VERSION:
  cutoff=POLICY['first_catalog_id']
  rows=current['entitlements']+current['consumed']
  if current.get('prepared') is not None:
   rows.append(current['prepared'])
  return {row['catalog_id']:row['catalog_id'] for row in rows if row['catalog_id']<cutoff}
 if not enabled(store):
  from .native_source_pack_presentation import aliases as source_aliases
  mapping=source_aliases(store,current,journal)
  vouchers=voucher_aliases(store,current,journal)
  if set(mapping)&set(vouchers) or set(mapping.values())&set(vouchers.values()):raise ValueError('Voucher/source caption collision')
  return {**mapping,**vouchers}
 if journal is None:
  from .local_purchase import PurchaseStore
  from .local_profile import ProfileStore
  journal=PurchaseStore(store.path.with_name('purchases.json'),ProfileStore(store.path.with_name('profile.json')),store).load()
 from .native_pack_sessions import legacy_state
 journal=legacy_state(journal,'purchases')
 from .native_paid_caption_reservations import validate_current
 validate_current(ACCOUNT,POLICY,current,journal)
 mapping=_aliases(current,journal,POLICY['first_catalog_id'],_currencies(POLICY),version=POLICY['version'])
 from .reward_release import aliases as reward_aliases
 rewards=reward_aliases(store,current,journal)
 if set(mapping)&set(rewards) or set(mapping.values())&set(rewards.values()):raise ValueError('Reward/paid caption collision')
 mapping={**mapping,**rewards}
 vouchers=voucher_aliases(store,current,journal)
 if set(mapping)&set(vouchers) or set(mapping.values())&set(vouchers.values()):raise ValueError('Voucher/paid caption collision')
 return {**mapping,**vouchers}

def validate_purchase(store,receipt,journal):
 from . import native_pack_sessions as sessions
 if sessions.selected(store.path.parent):
  if 'session_id' not in receipt:return # immutable pre-migration completed receipts
  e=sessions.current()
  if e is None or receipt['session_id']!=e['sid']:raise ValueError('Purchase epoch changed')
  from .local_store import products
  p=next((p for p in products(store.path.with_name('products.json')) if p['product_id']==receipt['sku_id']),None)
  price='coin_price' if receipt['currency']=='coins' else 'point_price'
  if p is None or p['definition']!=receipt['entitlement']['definition'] or p.get(price)!=receipt['amount'] or receipt['next_product_id']!=receipt['product_id']+1:raise ValueError('Session purchase policy conflict')
  candidate={**journal,'prepared':receipt}
  mapping=sessions.mapping(journal=candidate)
  if mapping.get(receipt['entitlement']['catalog_id'])!=receipt['product_id']:raise ValueError('Purchase alias conflict')
  return
 if not enabled(store):
  from .native_source_pack_presentation import validate_purchase as validate_source_purchase
  return validate_source_purchase(store,receipt,journal)
 # Check the prospective receipt while still holding the existing account lock,
 # before preparing a journal or touching the wallet. Retries keep their IDs.
 candidate={'persona_id':1,'receipts':journal['receipts'][:]}
 if not any(r['product_id']==receipt['product_id'] for r in candidate['receipts']):candidate['prepared']=receipt
 mapping=aliases(store,journal=candidate)
 from .local_store import active_offers
 internal={r['catalog_id'] for r in store.load()['entitlements']+store.load()['consumed']}
 internal.add(receipt['entitlement']['catalog_id'])
 active={r['product_id'] for r in active_offers(store.path.with_name('products.json'),candidate)}
 if internal&active or set(mapping.values())&active:raise ValueError('Active offer collides with pack presentation')

def validate_pack_state(store,value):
 from . import native_pack_sessions as sessions
 if POLICY is not None and POLICY.get('version')==FRESH_VERSION and enabled(store) and sessions.current() is None:
  # Startup validates ownership before the first genuine /ut/auth. Native
  # aliases are checked when commit_auth builds that account's first epoch.
  legacy_aliases(store,sessions.legacy_state(value,'packs'))
  return
 from . import native_free_packs as vouchers
 if enabled(store) or value.get('voucher_grants') or vouchers.ACCOUNT==store.path.parent.resolve():aliases(store,value=value)
 else:
  from .native_source_pack_presentation import validate_pack_state as validate_source_state
  validate_source_state(store,value)

def wire_id(store,key):return aliases(store).get(key,key)

def resolve_open(store,key):
 from . import native_pack_sessions as sessions
 mapping=aliases(store)
 if sessions.selected(store.path.parent):
  if key not in mapping.values():raise ValueError('Unknown native session pack')
  return next(k for k,w in mapping.items() if w==key)
 # Aliased durable IDs are private. Accept only the issued wire ID so one
 # ownership object cannot be addressed by two independent native retry keys.
 if key in mapping.values():return next(k for k,v in mapping.items() if v==key)
 if key in mapping and mapping[key]!=key:raise ValueError('Use issued purchased offer ID')
 return key

def project(value,store,*,pack_state=None):
 mapping=aliases(store,value=pack_state)
 if not mapping:return value
 rows=[{**r,'id':mapping.get(r['id'],r['id'])} if r.get('unopened') else r for r in value['purchase']]
 if len({r['id'] for r in rows})!=len(rows):raise ValueError('Catalog presentation collision')
 return {**value,'purchase':rows}
