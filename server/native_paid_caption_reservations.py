"""Opt-in prospective typed offer IDs for the original startup caption cache.

These IDs are local presentation policy, never historical EA SKUs. No ownership
or additional journal is created. Existing purchase receipts reserve successors.
"""
import hashlib
import json
from pathlib import Path

VERSION = 'native_paid_pack_presentation_v2'
VERSION_V3 = 'native_paid_pack_presentation_v3'
VERSION_V4 = 'native_paid_pack_presentation_v4'
VERSION_V5 = 'native_paid_pack_presentation_v5'
VERSION_V6 = 'native_paid_pack_presentation_v6'
VERSION_V7 = 'native_paid_pack_presentation_v7'
VERSION_V8 = 'native_paid_pack_presentation_v8'
VERSION_V9 = 'native_paid_pack_presentation_v9'
VERSIONS = (VERSION, VERSION_V3, VERSION_V4, VERSION_V5, VERSION_V6, VERSION_V7, VERSION_V8, VERSION_V9)
SLOTS = 32

def starts(version=VERSION):
    from .classic_pack_store import SUPPORTED_V10, SUPPORTED_V11
    if version not in VERSIONS:raise ValueError('Unknown paid caption version')
    if version==VERSION_V9:
        from .pack_family_split import starts as split_starts
        return {**starts(VERSION_V8),**split_starts()}
    if version==VERSION_V8:
        from .standard_pack_specs import catalog
        from .store_pool_amendment import starts as amended
        return {**{p['definition']:65000+i*SLOTS for i,p in enumerate(catalog()['products'])},**amended()}
    if version==VERSION_V7:
        from .club_item_packs import catalog
        #62000/62100 belong to existing Gold/Silver voucher captions.
        return {p['definition']:64000+i*SLOTS for i,p in enumerate(catalog()['products'])}
    bindings,first=(SUPPORTED_V10,50000) if version==VERSION else (SUPPORTED_V11,52000 if version==VERSION_V3 else 54000 if version==VERSION_V4 else 56000)
    result={definition: first + i*SLOTS for i, definition in enumerate(bindings.values())}
    if version==VERSION_V6:
        from .specialist_consumable_packs import policy
        result.update({definition:59000+i*SLOTS for i,definition in enumerate(policy()['pack_definitions'])})
    return result

def reserved(policy):
    return {i for row in policy['caption_bindings'].values()
            for i in range(row['first_offer_id'], row['first_offer_id']+SLOTS)}

def validate_origin(account, policy):
    origin = Path(policy['caption_origin_archive']).resolve()
    from . import store_release
    release = policy['version'] == VERSION_V4 or store_release.selected(account)
    if release:
        if not store_release.selected(account):raise ValueError('Explicit Store deployment required')
        deployment = store_release.validate(account)
        if policy['version']==VERSION_V6 and deployment['version']!='local_store_release_v3':
            raise ValueError('Specialist real deployment requires its own native certificate')
        if policy['version']==VERSION_V7 and deployment['version']!='local_store_release_v4':
            raise ValueError('Club-item real deployment requires its own native certificate')
        if policy['version']==VERSION_V8 and deployment['version']!='local_store_release_v5':
            raise ValueError('Exact-tier real deployment requires its own native certificate')
        if policy['version']==VERSION_V9 and 'pack_family_split' not in deployment:raise ValueError('Pack split requires certified deployment')
        expected=deployment['pack_family_split']['archive'] if policy['version']==VERSION_V9 else deployment['spec_archive'] if policy['version']==VERSION_V8 else deployment['club_archive'] if policy['version']==VERSION_V7 else deployment['specialist_archive'] if policy['version']==VERSION_V6 else deployment['upgrade_archive'] if policy['version']==VERSION_V5 else deployment['origin_archive']
        if str(origin) != expected:raise ValueError('Deployment caption origin differs')
    if (not release and origin.parent != account.parent) or origin == account:
        raise ValueError('Separate same-lab caption origin required')
    manifest = json.loads((origin/'.lab-snapshot.json').read_bytes())['sha256']
    for name, expected in manifest.items():
        path = origin/name
        if Path(name).name != name or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Caption origin changed')
    from .native_paid_pack_presentation import MARKER
    required_origin=VERSION_V8 if policy['version']==VERSION_V9 else VERSION_V7 if policy['version']==VERSION_V8 else VERSION_V6 if policy['version']==VERSION_V7 else 'native_paid_pack_presentation_v1' if policy['version']==VERSION else VERSION_V5 if policy['version']==VERSION_V6 else VERSION_V4 if policy['version']==VERSION_V5 else VERSION
    if release and policy['version']==VERSION_V4 and (origin/MARKER).exists():raise ValueError('Initial deployment must precede paid projection')
    if (not release or policy['version'] in (VERSION_V5,VERSION_V6,VERSION_V7,VERSION_V8,VERSION_V9)) and json.loads((origin/MARKER).read_bytes())['version'] != required_origin:
        raise ValueError('Caption origin must precede selected caption activation')
    from .local_store import products
    original_catalog = {r['product_id']: r for r in products(origin/'products.json')}
    catalog = original_catalog if policy['version']==VERSION else {r['product_id']: r for r in products(account/'products.json')}
    if policy['version'] in (VERSION_V5,VERSION_V6,VERSION_V7,VERSION_V8,VERSION_V9):
        from .store_fp_policy import validate_catalog
        validate_catalog(json.loads((account/'products.json').read_bytes()))
    bindings = policy['caption_bindings']
    if type(bindings) is not dict or not bindings:
        raise ValueError('Explicit prospective caption bindings required')
    seen = set()
    namespace=starts(policy['version'])
    for sku, row in bindings.items():
        if (type(sku) is not str or not sku.isdecimal() or str(int(sku)) != sku or
            type(row) is not dict or set(row) != {'definition', 'first_offer_id'} or
            row['definition'] not in namespace or type(row['first_offer_id']) is not int or
            row['first_offer_id'] != namespace[row['definition']] or row['definition'] in seen):
            raise ValueError('Invalid typed caption binding')
        product = catalog.get(int(sku))
        if product is None and policy['version']==VERSION_V9:
            previous=json.loads((origin/MARKER).read_bytes())['caption_bindings']
            if previous.get(sku)!=row:raise ValueError('Only an unchanged retired caption binding may survive')
            product=original_catalog.get(int(sku))
        if not product or product['definition'] != row['definition'] or not product.get('repeatable') or 'coin_price' not in product:
            raise ValueError('Caption binding must match an approved repeatable coin SKU')
        seen.add(row['definition'])
    old = json.loads((origin/'purchases.json').read_bytes())
    if old.get('prepared'):
        raise ValueError('Quiescent caption origin required')
    if policy['version'] in (VERSION_V3, VERSION_V4, VERSION_V5, VERSION_V6, VERSION_V7, VERSION_V8, VERSION_V9):
        prior_ids=set(original_catalog)
        for row in old['receipts']:
            prior_ids.update(row[k] for k in ('product_id','sku_id','next_product_id') if k in row)
        new_keys=set(bindings)
        if policy['version'] in (VERSION_V6,VERSION_V9):
            previous=json.loads((origin/MARKER).read_bytes())['caption_bindings']
            if any(bindings.get(k)!=v for k,v in previous.items()):raise ValueError('Specialist catalog must retain existing typed captions')
            new_keys-=set(previous)
        if prior_ids & {int(key) for key in new_keys}:
            raise ValueError('New policy requires never-issued SKU identities')
    return old['receipts']

def validate_current(account, policy, value, journal):
    if policy['version'] not in VERSIONS:
        return
    baseline = json.loads((Path(policy['caption_origin_archive'])/'purchases.json').read_bytes())['receipts']
    if journal['receipts'][:len(baseline)] != baseline:
        raise ValueError('Historical purchase receipts changed')
    bindings = policy['caption_bindings']; namespace = reserved(policy)
    from .local_store import products
    for row in products(account/'products.json'):
        binding = bindings.get(str(row['product_id']))
        if row['product_id'] in namespace or (binding and (row['definition'] != binding['definition'] or not row.get('repeatable') or 'coin_price' not in row)):
            raise ValueError('Catalog conflicts with typed captions')
    owned = {e['catalog_id'] for e in value['entitlements']+value['consumed']}
    if value.get('prepared'):
        owned.add(value['prepared']['catalog_id'])
    owned.update(r['entitlement']['catalog_id'] for r in journal['receipts']+([journal['prepared']] if journal.get('prepared') else []))
    if owned & namespace:
        raise ValueError('Ownership collides with prospective captions')
    history = journal['receipts']+([journal['prepared']] if journal.get('prepared') else [])
    historical_namespace=namespace
    if policy['version'] in (VERSION_V6,VERSION_V9):
        previous=json.loads((Path(policy['caption_origin_archive'])/'native-paid-pack-presentation.json').read_bytes())['caption_bindings']
        historical_namespace=namespace-reserved({'caption_bindings':previous})
    if any(r['product_id'] in historical_namespace or r.get('next_product_id') in historical_namespace for r in baseline):
        raise ValueError('Historical offer collides with prospective captions')
    for row in history[len(baseline):]:
        binding = bindings.get(str(row.get('sku_id')))
        if binding:
            first = binding['first_offer_id']; nxt = row.get('next_product_id')
            allowed=('coins','points') if policy['version'] in (VERSION_V5,VERSION_V6,VERSION_V7,VERSION_V8,VERSION_V9) else ('coins',)
            if (row['currency'] not in allowed or row['entitlement']['definition'] != binding['definition'] or
                type(nxt) is not int or not first <= nxt < first+SLOTS or
                (row['product_id'] in namespace and not first <= row['product_id'] < first+SLOTS)):
                raise ValueError('Prospective purchase conflicts with typed captions')
            if policy['version'] in (VERSION_V5,VERSION_V6,VERSION_V7,VERSION_V8,VERSION_V9):
                product=next((p for p in products(account/'products.json') if p['product_id']==row['sku_id']),None)
                if product is None:raise ValueError('Retired SKU cannot receive a new purchase')
                price_key='point_price' if row['currency']=='points' else 'coin_price'
                if product.get(price_key)!=row['amount']:raise ValueError('Prospective currency/price differs from admitted catalog')
        elif row['product_id'] in namespace or row.get('next_product_id') in namespace:
            raise ValueError('Foreign SKU uses typed caption namespace')

def _policy(path):
    from . import native_paid_pack_presentation as paid
    from .local_packs import PackStore
    store = PackStore(Path(path).with_name('packs.json'))
    if not paid.enabled(store) or paid.POLICY['version'] not in VERSIONS:
        return None
    return paid.POLICY

def successor(path, journal, sku, fallback):
    policy = _policy(path)
    if policy is None:
        return fallback
    from .local_packs import PackStore
    validate_current(Path(path).parent, policy, PackStore(Path(path).with_name('packs.json')).load(), journal)
    binding = policy['caption_bindings'].get(str(sku))
    if binding:
        history = journal['receipts']+([journal['prepared']] if journal.get('prepared') else [])
        recent = [r for r in history if r.get('sku_id') == sku and r.get('next_product_id') in range(binding['first_offer_id'], binding['first_offer_id']+SLOTS)]
        candidate = recent[-1]['next_product_id']+1 if recent else binding['first_offer_id']
        if candidate >= binding['first_offer_id']+SLOTS:
            raise ValueError('Prospective paid caption capacity exhausted before purchase')
        return candidate
    while fallback in reserved(policy):
        fallback += 1
    return fallback

def descriptions(store,*,value=None):
    policy = _policy(store.path)
    if policy is None:
        return []
    from .local_purchase import PurchaseStore
    from .local_profile import ProfileStore
    journal = PurchaseStore(store.path.with_name('purchases.json'), ProfileStore(store.path.with_name('profile.json')), store).load()
    validate_current(store.path.parent, policy, store.load() if value is None else value, journal)
    return [(key, row['definition']) for row in policy['caption_bindings'].values()
            for key in range(row['first_offer_id'], row['first_offer_id']+SLOTS)]
