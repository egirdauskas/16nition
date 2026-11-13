"""Explicit prospective Store-only policy amendment; old draws remain immutable."""
import copy,hashlib,json
from pathlib import Path
from .policy_memo import policy_memo
PATH=Path(__file__).parent/'policy/store-pool-amendment-v1.json'
POOL='training_injury_misc_no_crowd_v3'

def policy():
 p=json.loads(PATH.read_bytes())
 if p['version']!='store_pool_amendment_v1' or p['classification']!='revival_policy' or p['default_enabled'] is not False or p['excluded_subtypes']!=[232]:raise ValueError('Unapproved Store pool amendment')
 return p

def validate_definition(key,rule,definitions):
 row=next((r for r in policy()['bindings'] if r['definition']==key),None)
 if row is None:raise ValueError('Unapproved amended definition')
 expected={**definitions[row['previous_definition']],'consumable_pool':POOL}
 if row['label']=='Mega':expected.update(tier_counts={'bronze':0,'silver':0,'gold':30},minimum_gold=30)
 if rule!=expected or any(type(rule[k]) is not type(v) for k,v in expected.items()):raise ValueError('Amended guarantees differ from authorization')
 return rule

@policy_memo
def catalog():
 from .standard_pack_specs import catalog as previous
 value=copy.deepcopy(previous());bindings={r['previous_definition']:r for r in policy()['bindings']}
 for i,row in enumerate(value['products']):
  if row['definition'] in bindings:
   row['definition']=bindings[row['definition']]['definition'];row['product_id']=63001+i
 return value

def starts():return {r['definition']:64500+i*32 for i,r in enumerate(policy()['bindings'])}
def previous_definition(key):return next((r['previous_definition'] for r in policy()['bindings'] if r['definition']==key),key)

def documents(account,backup):
 from . import store_release,native_paid_pack_presentation as paid
 from .native_paid_caption_reservations import starts as all_starts,VERSION_V8
 account,backup=Path(account).resolve(),Path(backup).resolve()
 release=json.loads((backup/store_release.MARKER).read_bytes());marker=json.loads((backup/paid.MARKER).read_bytes())
 from .standard_pack_specs import catalog as previous
 if release['version']!='local_store_release_v5' or 'pool_amendment' in release or marker['version']!=VERSION_V8 or json.loads((backup/'products.json').read_bytes())!=previous():raise ValueError('Archived unamended certified Storev5 required')
 rows=catalog();namespace=all_starts(VERSION_V8)
 marker['caption_bindings']={str(r['product_id']):{'definition':r['definition'],'first_offer_id':namespace[r['definition']]} for r in rows['products']}
 def sha(v):return hashlib.sha256((json.dumps(v,indent=2)+'\n').encode()).hexdigest()
 release.update(account=str(account),products_sha256=sha(rows),presentation_sha256=sha(marker),pool_amendment={
  'version':policy()['version'],'policy_sha256':hashlib.sha256(PATH.read_bytes()).hexdigest(),
  'archive':str(backup),'manifest_sha256':hashlib.sha256((backup/'.lab-snapshot.json').read_bytes()).hexdigest()})
 return {'products.json':rows,paid.MARKER:marker,store_release.MARKER:release}

def validate_deployment(account,release):
 from . import store_release,native_paid_pack_presentation as paid
 a=release['pool_amendment']
 if set(a)!={'version','policy_sha256','archive','manifest_sha256'} or a['version']!=policy()['version'] or a['policy_sha256']!=hashlib.sha256(PATH.read_bytes()).hexdigest():raise ValueError('Store amendment policy changed')
 from . import gameplay_release
 owner=store_release.REAL if Path(account).resolve()!=store_release.REAL and gameplay_release.selected(account) else account
 backup=store_release.archive(a['archive'],a['manifest_sha256']);docs=documents(owner,backup)
 if release!=docs[store_release.MARKER] or json.loads((account/paid.MARKER).read_bytes())!=docs[paid.MARKER]:raise ValueError('Store amendment differs from archived prospective change')
 for name,key in (('purchases.json','receipts'),('packs.json','consumed')):
  before=json.loads((backup/name).read_bytes())[key];current=json.loads((account/name).read_bytes())[key]
  if current[:len(before)]!=before:raise ValueError('Pre-amendment receipts changed')
 return docs['products.json']
