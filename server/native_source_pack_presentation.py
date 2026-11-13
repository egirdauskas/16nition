"""Prospective, isolated source-pack caption reservation; disabled by default.

The original XML map is loaded at startup and indexed by numeric catalog ID.
Reserve a bounded, typed presentation namespace before any genuine new source;
descriptions confer no ownership. Existing PackStore source receipts supply each
permanent alias, including after consumption. No new entitlement/transaction
framework, invented artwork, product SKU, reward or football resource is used.
This candidate needs an independent original-client same-session certificate.
"""
import hashlib
import json
from pathlib import Path

ACCOUNT = None
POLICY = None
MARKER = 'native-source-pack-presentation.json'
VERSION = 'native_source_pack_presentation_v1'
VERSION_V2 = 'native_source_pack_presentation_v2'
VERSION_V3 = 'native_source_pack_presentation_v3'
VERSION_V4 = 'native_source_pack_presentation_v4'
SLOTS = 64
STARTS = {'revival_bronze_mixed_specials_v4': 60000,
          'revival_premium_bronze_mixed_specials_v4': 60064}
RESERVED = frozenset(w for first in STARTS.values() for w in range(first, first+SLOTS))
STARTS_V2 = {'revival_bronze_mixed_specials_v5': 60400,
             'revival_premium_bronze_mixed_specials_v5': 60464}


def starts(policy):
    # Historical frozen verifiers provide the original policy without version.
    version=policy.get('version',VERSION)
    if version in (VERSION_V3,VERSION_V4):
        from .reward_store_parity import policy as parity_policy
        from .revival_rewards import LABELS
        bindings=parity_policy()['bindings']
        if version==VERSION_V4:
            return {bindings[label]['definition']:57000+i*SLOTS for i,label in enumerate(LABELS)}
        return {**STARTS_V2,**{bindings[label]['definition']:61000+i*SLOTS for i,label in enumerate(LABELS)}}
    if version not in (VERSION,VERSION_V2):raise ValueError('Unknown source caption version')
    return STARTS_V2 if version==VERSION_V2 else STARTS


def reserved(policy):
    return frozenset(w for first in starts(policy).values() for w in range(first,first+SLOTS))


def validate_reward_policy(path):
    """Refuse mismatched policy/caption namespaces before accepting a fixture."""
    if POLICY is None:raise ValueError('Source presentation selector required')
    from .native_match_pack_policy import snapshot,championship_definition
    definitions=set(starts(POLICY))
    for division in (9,10):
        quote=snapshot(division,path)
        if (quote['version']=='reward_store_parity_v1')!=(POLICY['version']==VERSION_V3):
            raise ValueError('Store parity requires its own explicit source caption version')
        if any(row['definition'] not in definitions for row in quote['outcomes'].values()):
            raise ValueError('Reward/source caption versions differ')
        title=championship_definition(division,path)
        if title is not None and title not in definitions:raise ValueError('Title/source caption versions differ')


def configure(account=None):
    global ACCOUNT, POLICY
    ACCOUNT = POLICY = None
    if account is None:
        return
    from .startup import validate_simulation_discovery
    from . import native_paid_pack_presentation as paid
    account = Path(account).resolve()
    validated = validate_simulation_discovery([account/n for n in
        ('profile.json', 'football.json', 'content.json', 'packs.json', 'seasons.json', 'definition.json', 'control.json')])
    if validated.name != 'isolated-account' or paid.ACCOUNT is not None:
        raise ValueError('Source presentation requires its own isolated selector without paid presentation')
    raw = (account/MARKER).read_bytes()
    marker = json.loads(raw)
    if (type(marker) is not dict or set(marker) != {'version', 'classification', 'origin_archive'} or
        marker['version'] not in (VERSION,VERSION_V2,VERSION_V3) or marker['classification'] != 'isolated_prospective_projection'):
        raise ValueError('Invalid source presentation marker')
    origin = Path(marker['origin_archive']).resolve()
    if origin.parent != account.parent or origin == account:
        raise ValueError('Separate same-lab prospective origin required')
    manifest = json.loads((origin/'.lab-snapshot.json').read_bytes())['sha256']
    for name, expected in manifest.items():
        path = origin/name
        if Path(name).name != name or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Source presentation origin changed')
    if MARKER in manifest or paid.MARKER in manifest or (account/paid.MARKER).exists():
        raise ValueError('Origin must precede source-only projection activation')
    from .local_packs import PackStore
    baseline = PackStore(origin/'packs.json').load()
    if baseline.get('prepared'):
        raise ValueError('Quiescent source origin required')
    purchases = origin/'purchases.json'
    if purchases.exists() and json.loads(purchases.read_bytes()).get('prepared'):
        raise ValueError('Quiescent purchase origin required')
    policy = {'version':marker['version'],'marker_sha256': hashlib.sha256(raw).hexdigest(),
              'old_sources': baseline.get('source_grants', []),
              'first_catalog_id': baseline['next_catalog_id']}
    # Validate before installing any process-wide projection state.
    store = PackStore(account/'packs.json')
    _aliases(store, store.load(), policy)
    ACCOUNT, POLICY = account, policy


def enabled(store):
    if ACCOUNT is None:
        return False
    if store.path.resolve().parent != ACCOUNT:
        raise ValueError('Source presentation account differs')
    if hashlib.sha256((ACCOUNT/MARKER).read_bytes()).hexdigest() != POLICY['marker_sha256']:
        raise ValueError('Source presentation marker changed')
    return True


def _check_namespace(store, value, policy, journal=None):
    namespace=reserved(policy)
    ids = {e['catalog_id'] for e in value['entitlements']+value['consumed']}
    if value.get('prepared'):
        ids.add(value['prepared']['catalog_id'])
    if ids & namespace:
        raise ValueError('Internal ownership collides with reserved source captions')
    products = store.path.with_name('products.json')
    if products.exists():
        from .local_store import active_offers
        if {o['product_id'] for o in active_offers(products, journal)} & namespace:
            raise ValueError('Paid offer collides with reserved source captions')
    # A consumed paid offer must not later acquire an unrelated source meaning.
    purchases = store.path.with_name('purchases.json')
    if journal is None and purchases.exists():
        journal = json.loads(purchases.read_bytes())
    if journal:
        receipts = journal['receipts']+([journal['prepared']] if journal.get('prepared') else [])
        if {r['product_id'] for r in receipts} & namespace:
            raise ValueError('Paid receipt collides with reserved source captions')


def _aliases(store, value, policy, journal=None):
    _check_namespace(store, value, policy, journal)
    namespace=starts(policy)
    old = policy['old_sources']
    sources = value.get('source_grants', [])
    if sources[:len(old)] != old:
        raise ValueError('Historical source receipts changed')
    mapping = {}
    owned = {e['catalog_id']: e for e in value['entitlements']+value['consumed']}
    for source in sources[len(old):]:
        e = source['entitlement']
        definition, key = e['definition'], e['catalog_id']
        if policy.get('version') in (VERSION_V3,VERSION_V4) and definition not in STARTS_V2:
            if source['policy_version']!='reward_store_parity_v1' or e.get('untradeable') is not True:
                raise ValueError('Prospective Store source requires untradeable reward ownership')
        if (definition not in namespace or key < policy['first_catalog_id'] or key in mapping or
            source['source_kind'] not in ('fixture', 'season') or key not in owned or
            any(owned[key].get(k) != v for k, v in e.items())):
            raise ValueError('Unsupported or conflicting prospective source presentation')
        # The archived allocator fixes the ordinal independently of list order,
        # consumption or restarts. Intervening paid allocations spend capacity;
        # an issued caption ID is never reassigned to another source.
        ordinal = key-policy['first_catalog_id']
        if ordinal >= SLOTS:
            raise ValueError('Reserved source caption capacity exhausted')
        mapping[key] = namespace[definition]+ordinal
    return mapping


def aliases(store, value=None, journal=None):
    if not enabled(store):
        return {}
    return _aliases(store, store.load() if value is None else value, POLICY, journal)


def candidate_store_reward(store,receipt):
    """Explicit isolated opening admission for a genuine prospective source.

    The draw still passes the normal resource/class renderability guard. This
    selector admits a bounded experiment, not native certification of all tiers.
    """
    from .reward_release import selected as released,aliases as release_aliases
    if released(store.path.parent):
        return receipt.get('untradeable') is True and receipt['catalog_id'] in release_aliases(store)
    if not enabled(store) or POLICY['version']!=VERSION_V3:return False
    value=store.load()
    if receipt.get('untradeable') is not True or receipt['catalog_id'] not in aliases(store,value):return False
    return any(s['policy_version']=='reward_store_parity_v1' and
               all(s['entitlement'].get(k)==receipt.get(k) for k in ('catalog_id','definition','untradeable'))
               for s in value.get('source_grants',[]))


def descriptions(store,*,value=None):
    if not enabled(store):
        return []
    aliases(store,value)  # Refuse collisions before returning any candidate XML.
    return [(wire, definition) for definition, first in starts(POLICY).items() for wire in range(first, first+SLOTS)]


def validate_capacity(store, count):
    if not enabled(store):
        return
    if type(count) is not int or count < 0:
        raise ValueError('Invalid prospective source count')
    value = store.load()
    aliases(store, value)
    if value['next_catalog_id']-POLICY['first_catalog_id']+count > SLOTS:
        raise ValueError('Reserve source caption capacity before accepting fixture')
    if set(range(value['next_catalog_id'], value['next_catalog_id']+count)) & reserved(POLICY):
        raise ValueError('Prospective internal allocation collides with source captions')


def validate_purchase(store, receipt, journal):
    if not enabled(store):
        return
    candidate = {**journal, 'receipts': journal['receipts'][:]}
    if not any(r['product_id'] == receipt['product_id'] for r in candidate['receipts']):
        candidate['prepared'] = receipt
    value = store.load()
    if receipt['entitlement']['catalog_id'] in reserved(POLICY):
        raise ValueError('Paid allocation collides with source caption namespace')
    aliases(store, value, candidate)


def validate_pack_state(store, value):
    if enabled(store):
        aliases(store, value)
