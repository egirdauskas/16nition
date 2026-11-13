"""Opt-in native pack epochs. Authentication metadata, not a second journal.

Native IDs remain 16 bit and permanently typed. Purchase/open receipts bind the
real SID; a closed session can only read completed operations. Ownership IDs are
private and monotonic. Wallet/inventory commits retain their existing journals.
"""
import hashlib,json,uuid
from bisect import bisect_right
from pathlib import Path
from .account_transaction import atomic,account_locked
ROOT=Path(__file__).resolve().parents[1]
ACCOUNT=POLICY=None
RAW_SID=b'x-fifa-local-original-sid'
VERSION='native_pack_sessions_v2'
PRIVATE_VERSION='private_pack_identity_v2'
PRIVATE_MAX=0x7ffffffffffffffe
FIRST=17000
SLOTS=128
DESCRIPTOR_LOOKAHEAD=16
MARKER='pack-session-release.json'
REAL=ROOT/'server/data/development/fm16in2026'

def bank():return {'version':'native_pack_bank_v1','first_wire_id':FIRST,'slots_per_definition':SLOTS}


def single_bank_selected():
    from .store_single_caption_bank import VERSION as single_version
    return POLICY is not None and POLICY.get('bank', {}).get('version') == single_version


def slot_layout():
    if single_bank_selected():
        from .store_single_caption_bank import profile
        value = profile()
        if POLICY['bank']['profile_sha256'] != value['sha256']:
            raise ValueError('Single-card caption profile changed during runtime')
        # STORE-006: selected demo offers append their own blocks after the bank.
        from .store_demo_offers import layout as demo_layout
        extra = demo_layout(ACCOUNT)
        end = max(first + count for first, count in value['layout'].values())
        if extra and (min(first for first, _ in extra.values()) < end or set(extra) & set(value['layout'])):
            raise ValueError('Demo offer caption block overlaps the single-card bank')
        return {**value['layout'], **extra}
    return {d: (FIRST + n * SLOTS, SLOTS) for n, d in enumerate(definitions())}


def _counts(mapping, layout):
    names = tuple(layout)
    starts = tuple(layout[d][0] for d in names)
    counts = {d: 0 for d in names}
    for wire_id in mapping.values():
        index = bisect_right(starts, wire_id) - 1
        if index < 0:
            continue
        definition = names[index]
        first, count = layout[definition]
        if wire_id < first + count:
            counts[definition] += 1
    return counts

def selected(account):
 if ACCOUNT is None or account is None or Path(account).resolve()!=ACCOUNT or POLICY['version']!=VERSION:return False
 if POLICY.get('fresh_account'):
  from . import fresh_account_runtime as fresh
  if not fresh.selected(ACCOUNT):
   return False
  if fresh.marker_sha(ACCOUNT) != POLICY['fresh_marker_sha256']:
   raise ValueError('Fresh account runtime policy changed')
  return True
 if 'selector_path' in POLICY and hashlib.sha256(Path(POLICY['selector_path']).read_bytes()).hexdigest()!=POLICY['selector_sha256']:raise ValueError('Pack-session selector changed')
 return True

def configure(account=None):
 global ACCOUNT,POLICY
 ACCOUNT=POLICY=None
 if account is None:return
 account=Path(account).resolve()
 from . import fresh_account_runtime as fresh
 if fresh.selected(account):
  configuration=fresh.validate(account)
  from .store_single_caption_bank import bank as single_bank
  marker_sha=fresh.marker_sha(account)
  if type(configuration.get('initial_catalog_id')) is not int or not 30001<=configuration['initial_catalog_id']<=PRIVATE_MAX:
   raise ValueError('Invalid fresh-account pack allocator')
  if json.loads((account/'packs.json').read_bytes()).get('identity_version')!=PRIVATE_VERSION:
   raise ValueError('Fresh account requires private pack identity')
  ACCOUNT, POLICY = account, {
   'version': VERSION, 'account': str(account), 'bank': single_bank(),
   'fresh_account': True, 'initial_catalog_id': configuration['initial_catalog_id'],
   'fresh_marker_sha256': marker_sha,
  }
  load()
  return
 deployed=account==REAL
 if not deployed and (ROOT/'reports' not in account.parents or account.name!='isolated-account' or not (account/'.lab-snapshot.json').is_file()):raise ValueError('Uncertified pack sessions require archived isolated account')
 marker=account/(MARKER if deployed else 'pack-session-candidate.json')
 v=json.loads(marker.read_bytes())
 if v.get('version')=='native_pack_session_probe_v1':
  if deployed:raise ValueError('Uncertified SID probe cannot be deployed')
  if set(v)!={'version','account','sid'} or v['account']!=str(account) or not isinstance(v['sid'],str) or not v['sid'].startswith('fifa16-pack-probe-') or len(v['sid'])!=50:raise ValueError('Invalid isolated SID probe')
 else:
  fields={'version','account','archive','manifest_sha256','products_sha256','bank'}
  if deployed:fields|={'certificate','certificate_sha256'}
  if set(v)!=fields or v['version']!=VERSION or v['account']!=str(account):raise ValueError('Invalid session policy')
  if v['bank'] != bank():
   from .store_single_caption_bank import bank as single_bank
   if v['bank'] != single_bank():
    raise ValueError('Invalid session policy: unknown caption bank')
   if deployed:
    # The append-only single-card bank deploys only with the certified
    # specific-card Store selector (native direct-delivery certificate).
    from .store_single_candidate import selection as single_selection
    if single_selection(account) is None:
     raise ValueError('Invalid session policy: new caption banks are isolated-only without a certified Store selector')
  if deployed:
   proof=Path(v['certificate']).resolve()
   if ROOT/'reports/pack-identity-renewal' not in proof.parents or hashlib.sha256(proof.read_bytes()).hexdigest()!=v['certificate_sha256']:raise ValueError('Pack-session certificate changed')
   c=json.loads(proof.read_bytes())
   if c.get('status')!='STOCK_VERIFIED_PACK_IDENTITY_RENEWAL' or c.get('bank')!=bank() or any(c.get(k) is not True for k in ('purchase_verified','opening_storage_verified','epoch_reuse_verified','source_pack_verified','restart_verified','exact_retry_verified','legacy_preserved','backend_boundaries_verified')):raise ValueError('Pack-session certificate incomplete')
  archive=Path(v['archive']).resolve()
  if ROOT/'reports' not in archive.parents or archive==account or account in archive.parents:raise ValueError('Separate migration archive required')
  if hashlib.sha256((archive/'.lab-snapshot.json').read_bytes()).hexdigest()!=v['manifest_sha256']:raise ValueError('Migration manifest changed')
  files=json.loads((archive/'.lab-snapshot.json').read_bytes())['sha256']
  if not {'packs.json','purchases.json','profile.json','products.json'}<=files.keys():raise ValueError('Incomplete migration archive')
  for n,h in files.items():
   p=archive/n
   if Path(n).name!=n or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=h:raise ValueError('Migration archive changed')
  if hashlib.sha256((account/'products.json').read_bytes()).hexdigest()!=v['products_sha256']:raise ValueError('Session catalog changed')
  if json.loads((account/'packs.json').read_bytes()).get('identity_version')!=PRIVATE_VERSION:raise ValueError('Private pack schema upgrade incomplete')
  old=json.loads((archive/'packs.json').read_bytes())
  if old.get('prepared') or json.loads((archive/'purchases.json').read_bytes()).get('prepared'):raise ValueError('Quiescent migration required')
  before=json.loads((archive/'profile.json').read_bytes());current=json.loads((account/'profile.json').read_bytes())
  if any(before[k]!=current[k] for k in ('persona_id','identity_pid','user_id')):raise ValueError('Migration owner changed')
  if v['bank'] != bank():
   from .store_single_caption_bank import profile as single_profile
   original_products = json.loads((archive / 'products.json').read_bytes())['products']
   original_names = sorted({p['definition'] for p in original_products})
   legacy = single_profile()['policy']['legacy_definitions']
   if legacy[:len(original_names)] != original_names:
    raise ValueError('Single-card caption migration changes historical Store aliases')
 ACCOUNT,POLICY=account,{**v,'selector_path':str(marker),'selector_sha256':hashlib.sha256(marker.read_bytes()).hexdigest()}
 if v['version']==VERSION:
  load()
  from .native_paid_caption_reservations import reserved
  from .reward_capacity import starts as earned_starts,SLOTS as earned_slots
  from .native_free_packs import RULES,SLOTS as voucher_slots
  policy=json.loads((account/'native-paid-pack-presentation.json').read_bytes())
  old_ids=reserved(policy)
  old_ids.update(i for first in earned_starts().values() for i in range(first,first+earned_slots))
  old_ids.update(i for d,version,first in RULES.values() for i in range(first,first+voucher_slots))
  new_ids = {i for first, count in slot_layout().values() for i in range(first, first + count)}
  if new_ids&old_ids:raise ValueError('Session caption namespace collision')

def origin():return Path(POLICY['archive'])

def initial_catalog_id():
 if POLICY.get('fresh_account'):
  return POLICY['initial_catalog_id']
 return json.loads((origin()/'packs.json').read_bytes())['next_catalog_id']

def definitions():
    from .local_store import products
    from .native_tournament_catalog import ACCOUNT as tournament_account
    from .native_tournament_match import REWARDS

    if single_bank_selected():
        return tuple(slot_layout())
    names = tuple(sorted({p['definition'] for p in products(ACCOUNT / 'products.json')}))
    if (
        ACCOUNT == tournament_account and REWARDS is not None
        and REWARDS.get('version') == 'tournament_rewards_v2'
    ):
        from .tournament_reward_policy import allowed_pack_definitions
        # Append only: historical session aliases must keep their bank offsets.
        names += tuple(sorted(allowed_pack_definitions() - set(names)))
    if FIRST + len(names) * SLOTS > 30001:
        raise ValueError('Session caption bank overflow')
    return names

def pending_descriptions(account):
    """Describe the exact future fresh-account bank before genuine CreateUser.

    These are display reservations only; no epoch, offer or entitlement is issued.
    """
    from .first_run_account import pending_session
    if pending_session(account) is None:
        return []
    from .store_single_caption_bank import layout as single_layout
    from .store_demo_offers import policy as demo_policy
    from .welcome_gift import policy as welcome_policy
    layout = single_layout()
    extra = {row['definition']: tuple(row['wire_block']) for row in demo_policy()['offers']}
    if extra and (set(layout) & set(extra) or min(first for first, _ in extra.values()) <
                  max(first + count for first, count in layout.values())):
        raise ValueError('Pending caption layout overlaps existing bank')
    layout.update(extra)
    gift = welcome_policy()['grant']['packs']
    if gift['definition'] not in layout:
        raise ValueError('Welcome pack absent from approved caption bank')
    rows = []
    for definition, (first, count) in layout.items():
        carried = gift['count'] if definition == gift['definition'] else 0
        rows.extend((first + index, definition)
                    for index in range(min(count, carried + DESCRIPTOR_LOOKAHEAD)))
    # Fresh profile initial_catalog_id follows its initial five grants; existing
    # legacy descriptions remain available alongside their actual session aliases.
    rows.extend((30001 + index, gift['definition']) for index in range(gift['count']))
    from .native_free_packs import RULES, SLOTS as voucher_slots
    rows.extend((index, definition) for definition, _, first in RULES.values()
                for index in range(first, first + voucher_slots))
    return rows


def descriptions():
 if not selected(ACCOUNT):return []
 from .local_packs import PackStore
 from .native_paid_pack_presentation import legacy_aliases
 packs=PackStore(ACCOUNT/'packs.json').load();old=legacy_state(packs,'packs');m=legacy_aliases(PackStore(ACCOUNT/'packs.json'),old)
 # STORE-006 (1507-1511): three texts for every reserved wire id made the sheet so large that one more
 # entry blanked every Store text. Describe only ids in use this session (issued offers and carried
 # unopened packs) plus a short lookahead of upcoming offer ids; the client refetches the sheet at login.
 layout = slot_layout()
 issued = _counts(mapping(pack_state=packs), layout) if current() is not None else {d: 0 for d in layout}
 rows = [(first + n, d) for d, (first, count) in layout.items()
         for n in range(min(count, issued.get(d, 0) + DESCRIPTOR_LOOKAHEAD))]
 rows.extend((m.get(r['catalog_id'],r['catalog_id']),r['definition']) for r in old['entitlements'])
 from .native_free_packs import RULES,SLOTS as voucher_slots
 rows.extend((i,d) for d,version,first in RULES.values() for i in range(first,first+voucher_slots))
 if len({i for i,d in rows})!=len(rows):
  seen={}
  for i,d in rows:
   if i in seen and seen[i]!=d:raise ValueError('Session descriptor collision')
   seen[i]=d
  rows=list(seen.items())
 return rows
def code(n, *, account=None):
 owner=ACCOUNT if account is None else Path(account)
 return 'fifa16-pack-code-'+uuid.uuid5(uuid.NAMESPACE_URL,str(owner)+':'+str(n)).hex
def sid(token):return 'fifa16-pack-'+hashlib.sha256(token.encode()).hexdigest()[:32]
def load():
 p=ACCOUNT/'pack-sessions.json';v=json.loads(p.read_bytes()) if p.exists() else {'version':VERSION,'epochs':[]}
 if set(v)!={'version','epochs'} or v['version']!=VERSION or type(v['epochs']) is not list:raise ValueError('Invalid sessions')
 purchases=ACCOUNT/'purchases.json'
 history=json.loads(purchases.read_bytes()) if purchases.exists() else {'receipts':[]}
 recorded=history['receipts']+([history['prepared']] if history.get('prepared') else [])
 known={e.get('sid') for e in v['epochs'] if type(e) is dict}
 if any('session_id' in r and r['session_id'] not in known for r in recorded):raise ValueError('Pack session metadata missing or rolled back')
 if not v['epochs']:
  raw=json.loads((ACCOUNT/'packs.json').read_bytes())
  if raw['next_catalog_id']!=initial_catalog_id():raise ValueError('Pack session metadata missing after allocation')
 tokens=[e.get('code') for e in v['epochs'] if type(e) is dict]
 if len(set(tokens))!=len(tokens):raise ValueError('Duplicate authentication epoch')
 previous=30001
 for n,e in enumerate(v['epochs'],1):
  if (set(e)!={'number','code','sid','first_catalog_id','carry'} or type(e['number']) is not int or e['number']!=n or type(e['code']) is not str or len(e['code'])!=49 or not e['code'].startswith('fifa16-pack-code-') or any(c not in '0123456789abcdef' for c in e['code'][17:]) or e['sid']!=sid(e['code']) or type(e['first_catalog_id']) is not int or not previous<=e['first_catalog_id']<=PRIVATE_MAX or type(e['carry']) is not list or any(type(k) is not int or not 30001<=k<e['first_catalog_id'] for k in e['carry']) or len(set(e['carry']))!=len(e['carry'])):raise ValueError('Invalid pack epoch')
  previous=e['first_catalog_id']
 return v

def current():
 rows=load()['epochs'];return rows[-1] if rows else None

def auth_code():
 if selected(ACCOUNT):return code(len(load()['epochs'])+1)
 from .mobile_setup_session import code as setup_code
 return setup_code() or 'fifa16-local-fut-code'
def auth_sid(token='fifa16-local-fut-code'):
 from .game_auth import SID
 if ACCOUNT is None:
  from .mobile_setup_session import sid as setup_sid
  return setup_sid(token) or (SID if token=='fifa16-local-fut-code' else None)
 if POLICY['version']!=VERSION:return POLICY['sid'] if token=='fifa16-local-fut-code' else None
 return sid(token) if token==auth_code() or any(e['code']==token for e in load()['epochs']) else None

@account_locked
def commit_auth(method,target,headers,body):
 if not selected(ACCOUNT):
  from .mobile_setup_session import record as record_setup
  record_setup(method,target,headers,body)
  return
 if method!='POST' or target!='/ut/auth':return
 from . import game_auth
 if game_auth.response_for(method,target,headers,body) is None:raise ValueError('Invalid session auth')
 token=json.loads(body.rstrip(b'\0'))['identification']['authCode'];v=load()
 if any(e['code']==token for e in v['epochs']):return
 from .local_packs import PackStore
 packs=PackStore(ACCOUNT/'packs.json').load();purchases=json.loads((ACCOUNT/'purchases.json').read_bytes())
 if packs.get('prepared') or purchases.get('prepared'):raise ValueError('Recover pack operation before renewal')
 native=ACCOUNT/'native-seasons.json'
 if native.exists():
  state=json.loads(native.read_bytes())
  if state.get('prepared') or (state.get('active_match') and not state['active_match'].get('committed')):raise ValueError('Finish or recover active match before renewal')
 e={'number':len(v['epochs'])+1,'code':token,'sid':sid(token),'first_catalog_id':packs['next_catalog_id'],'carry':sorted(r['catalog_id'] for r in packs['entitlements'])}
 mapping(pack_state=packs,epoch=e)
 v['epochs'].append(e);atomic(ACCOUNT/'pack-sessions.json',(json.dumps(v,indent=2,sort_keys=True)+'\n').encode())

def normalize(headers):
 from .game_auth import SID
 if ACCOUNT is None:
  from .mobile_setup_session import code as setup_code,sid as setup_sid
  token=setup_code()
  if token is not None and headers.get(b'x-ut-sid')==setup_sid(token).encode():
   return {**headers,b'x-ut-sid':SID.encode()}
  return headers
 h=dict(headers);h.pop(RAW_SID,None);actual=h.get(b'x-ut-sid')
 if actual is None:return h
 allowed=([POLICY['sid']] if POLICY['version']!=VERSION else [e['sid'] for e in load()['epochs']]+[SID])
 if actual.decode('ascii') not in allowed:raise ValueError('Unknown native SID')
 h[RAW_SID]=actual;h[b'x-ut-sid']=SID.encode();return h

def is_stale(headers):
 if not selected(ACCOUNT) or RAW_SID not in headers:return False
 e=current();return e is None or headers[RAW_SID]!=e['sid'].encode()

def legacy_state(v,kind):
 if not selected(ACCOUNT):return v
 cutoff=initial_catalog_id()
 if kind=='purchases':return {'persona_id':1,'receipts':[r for r in v['receipts'] if 'session_id' not in r]}
 return {**v,'entitlements':[r for r in v['entitlements'] if r['catalog_id']<cutoff],'consumed':[r for r in v['consumed'] if r['catalog_id']<cutoff],'source_grants':[r for r in v.get('source_grants',[]) if r['entitlement']['catalog_id']<cutoff],'voucher_grants':[r for r in v.get('voucher_grants',[]) if r['entitlement']['catalog_id']<cutoff]}

def mapping(*,pack_state=None,journal=None,epoch=None):
 from .local_packs import PackStore
 packs=PackStore(ACCOUNT/'packs.json').load() if pack_state is None else pack_state;e=current() if epoch is None else epoch
 if e is None:
  if packs['entitlements']:raise ValueError('Authenticate before accessing unopened packs')
  return {}
 owned={r['catalog_id']:r for r in packs['entitlements']+packs['consumed']}
 if journal is None:journal=json.loads((ACCOUNT/'purchases.json').read_bytes())
 if journal.get('prepared'):
  r=journal['prepared']['entitlement'];owned.setdefault(r['catalog_id'],r)
 keys=set(e['carry'])|{k for k in owned if k>=e['first_catalog_id']}
 if not keys<=owned.keys():raise ValueError('Epoch ownership disappeared')
 layout = slot_layout()
 counts = {d: 0 for d in layout}
 result = {}
 for k in sorted(keys):
  d=owned[k]['definition']
  if d not in counts:
   vouchers={r['entitlement']['catalog_id']:r['wire_id'] for r in packs.get('voucher_grants',[])}
   if k in vouchers:result[k]=vouchers[k];continue
   from .native_paid_pack_presentation import legacy_aliases
   legacy=legacy_aliases(PackStore(ACCOUNT/'packs.json'),legacy_state(packs,'packs'))
   if k not in legacy:raise ValueError('No supported legacy caption')
   result[k]=legacy[k];continue
  first, count = layout[d]
  if counts[d] >= count:
   raise ValueError('Session capacity exhausted; restart client')
  result[k] = first + counts[d]
  counts[d] += 1
 if len(set(result.values()))!=len(result):raise ValueError('Session alias collision')
 return result

def offers(path,journal):
 from .local_store import products
 layout = slot_layout()
 mapped = mapping(journal=journal) if current() else {}
 counts = _counts(mapped, layout)
 return [
     {**p, 'sku_id': p['product_id'],
      'product_id': layout[p['definition']][0] + counts[p['definition']]}
     for p in products(path)
     if counts[p['definition']] < layout[p['definition']][1] - 1
 ]

def validate_capacity(store,count,required):
 if type(count) is not int or count<0:raise ValueError('Invalid reward capacity')
 layout = slot_layout()
 counts = _counts(mapping(pack_state=store.load()), layout)
 needed = required if required is not None else {d: count for d in layout}
 if any(d not in counts or type(n) is not int or n < 0 or counts[d] + n > layout[d][1]
        for d, n in needed.items()):
  raise ValueError('Renew native session before match')

def prior_purchase(v,key):
 e=current();return next((r for r in v['receipts']+([v['prepared']] if v.get('prepared') else []) if r.get('session_id')==(e['sid'] if e else None) and r['product_id']==key),None)
def opening_identity(key):return {'sid':current()['sid'],'wire_id':key}

def stale_reply(method,target,headers,body,store,football):
 from .pack_protocol import purchase_request,open_key,encode_purchase,encode_open
 from .game_auth import SID
 raw=headers.get(RAW_SID,b'').decode('ascii');paid=purchase_request(method,target,headers,body)
 if paid is not None:
  rows=json.loads(store.path.with_name('purchases.json').read_bytes())['receipts'];r=next((r for r in rows if r['product_id']==paid[0] and r.get('session_id',SID)==raw),None)
  if r is None or r['currency']!=paid[1]:raise ValueError('No completed closed-session purchase')
  if r.get('delivery')=='direct':
   from .pack_protocol import encode_paid_reply
   return encode_paid_reply(r,store,football)
  return encode_purchase(r)
 key=open_key(method,target,headers,body,allow_reserved=True)
 if key is not None:
  rows=store.load()['consumed'];r=next((r for r in rows if r.get('opening_identity')=={'sid':raw,'wire_id':key}),None)
  if r is None and raw==SID:
   from .native_paid_pack_presentation import legacy_aliases
   if POLICY.get('fresh_account'):
    baseline=legacy_state(json.loads((ACCOUNT/'packs.json').read_bytes()),'packs')
   else:
    baseline=json.loads((origin()/'packs.json').read_bytes())
   m=legacy_aliases(store,baseline);k=next((k for k,w in m.items() if w==key),key)
   r=next((r for r in rows if r['catalog_id']==k and k<initial_catalog_id()),None)
  if r is None:raise ValueError('No completed closed-session opening')
  return encode_open(r,football,key)
 raise ValueError('Closed session only permits completed pack retries')
