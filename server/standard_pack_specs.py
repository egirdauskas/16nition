"""Exact tier/rarity guarantees for the existing products; immutable old draws.

Numbers follow the user-approved historical console reference. Selection odds
remain revival policy. This introduces no new visible pack product or resource.
"""
import copy,hashlib,itertools,json
from pathlib import Path
from .policy_memo import policy_memo
PATH=Path(__file__).parent/'policy/standard-pack-specs-v1.json'
SELECTION='typed_tier_quota_v1'
TIERS=('bronze','silver','gold')

def policy():
    p=json.loads(PATH.read_bytes())
    if (p.get('version')!='standard_pack_specs_v1' or p.get('classification')!='revival_policy' or
        p.get('default_enabled') is not False or p.get('stock_delivery_enabled') is not False or
        p.get('selection')!=SELECTION or p.get('new_product_types') is not False):
        raise ValueError('Unapproved standard pack specifications')
    return p

def validate_definition(key,rule,definitions=None):
    from .pack_family_split import DEFINITIONS as split_definitions,validate_definition as split_validate
    if key in split_definitions:return split_validate(key,rule)
    if definitions is None:
        from .local_packs import DEFINITIONS as definitions
    from .local_club_items import POOL
    p=policy();source=next((r for r in [*p['standard_bindings'].values(),p['consumer']] if r['definition']==key),None)
    if source is None:
        from .store_pool_amendment import validate_definition as amended
        return amended(key,rule,definitions)
    old=definitions[source['previous_definition']]
    expected={**old,'selection':SELECTION,'tier_counts':source['tier_counts']}
    if source is p['consumer']:expected.update(item_family='non_player',club_item_pool=POOL)
    else:expected['minimum_'+old['quality']]=source['tier_counts'][old['quality']]
    counts=source['tier_counts']
    if (rule!=expected or any(type(rule[k]) is not type(v) for k,v in expected.items()) or
        set(counts)!=set(TIERS) or any(type(n) is not int or n<0 for n in counts.values()) or
        sum(counts.values())!=rule['item_count'] or rule['exact_rare'] is not True):
        raise ValueError('Exact tier/rarity definition differs from authorized specification')
    return rule

@policy_memo
def bindings():
    from .club_item_packs import bindings as previous
    from .pack_policy import load_definitions
    p=policy();old=previous();new={**old}
    if set(p['standard_bindings'])|set(p['unchanged_standard_bindings'])!=set(old):raise ValueError('Complete unchanged standard catalog required')
    for name,row in p['standard_bindings'].items():
        if row['previous_definition']!=old[name] or row['definition']==old[name]:raise ValueError('New immutable definition required')
        new[name]=row['definition']
    if p['unchanged_standard_bindings']!={n:d for n,d in old.items() if n not in p['standard_bindings']}:
        raise ValueError('Player-only packs, including Premium Gold Players, must remain unchanged')
    definitions=load_definitions()
    for row in [*p['standard_bindings'].values(),p['consumer']]:validate_definition(row['definition'],definitions[row['definition']],definitions)
    return new

@policy_memo
def catalog():
    from .club_item_packs import catalog as previous
    p=policy();value=copy.deepcopy(previous());value['version']='local_store_catalog_v5';new=bindings()
    replacements={r['previous_definition']:r['definition'] for r in p['standard_bindings'].values()}
    replacements[p['consumer']['previous_definition']]=p['consumer']['definition']
    for n,row in enumerate(value['products']):
        row['definition']=replacements.get(row['definition'],row['definition'])
        row['product_id']=62501+n  # Local service identities; not EA product IDs.
    return value

def pool(rule):
    if rule['item_family'] in ('consumable','club_item'):
        from .pack_family_split import pool as family_pool
        return family_pool(rule)
    from .local_packs import MixedPull
    from .local_consumables import pack_references
    from .local_club_items import references,quality
    allowed={t for t,n in rule['tier_counts'].items() if n}
    result=[]
    if rule['item_family']!='non_player':
        from .card_pool import card_index
        from .reconstructed_specials import reviewed_pool
        result += [MixedPull(c.resource_id,None,c.rare,c.quality) for c in card_index().values() if c.lookup_supported and c.quality in allowed]
        result += [MixedPull(v.base_resource_id,v.record_id,v.pack_eligibility['base_rare'],v.pack_eligibility['base_quality'])
                   for v in reviewed_pool() if v.pack_eligibility['base_quality'] in allowed]
    result += [MixedPull(rid,None,int(r['weightrare']>0),quality(r),'consumable')
               for rid,r in pack_references(rule['consumable_pool']).items() if quality(r) in allowed]
    result += [MixedPull(rid,None,r['rare'],quality(r),r['item_type'])
               for rid,r in references().items() if quality(r) in allowed]
    return tuple(result)

def select_pulls(definition,catalog_id,rule,*,private_identity_version=None):
    from .local_packs import mixed_counts_rare
    validate_definition(definition,rule)
    if private_identity_version not in (None,'private_pack_identity_v2'):raise ValueError('Unknown private identity version')
    limit=0x7ffffffffffffffe if private_identity_version=='private_pack_identity_v2' else 65535
    if type(catalog_id) is not int or not 30001<=catalog_id<=limit:raise ValueError('Full entitlement identity required')
    eligible=pool(rule)
    from .pack_draw_cache import selected
    from .pack_special_rates import rates_for
    rates = rates_for(rule)
    return selected(('typed_tier_quota_v1',_select_from_pool,mixed_counts_rare),
        (definition,catalog_id,private_identity_version,rates),rule,eligible,
        lambda:_select_from_pool(definition,catalog_id,rule,eligible))

def _select_from_pool(definition,catalog_id,rule,eligible):
    from .local_packs import mixed_counts_rare
    from .pack_special_rates import rates_for, probabilities, pick, slot_rare
    rates = rates_for(rule)
    chances = probabilities(eligible, rates) if rates else None
    groups={(t,r):[] for t in TIERS for r in (False,True)}
    for item in eligible:
        # pack_special_rates_v1: specials follow their base rarity when active.
        rare = slot_rare(item) if rates else mixed_counts_rare(item, rule)
        groups[item.base_quality, rare].append(item)
    resources={k:{p.resource_id for p in rows} for k,rows in groups.items()}
    counts=rule['tier_counts']
    plans=[p for p in itertools.product(*(range(counts[t]+1) for t in TIERS))
           if sum(p)==rule['minimum_rare'] and all(
               p[i]<=len(resources[t,True]) and counts[t]-p[i]<=len(resources[t,False]) and
               counts[t]<=len(resources[t,True]|resources[t,False]) for i,t in enumerate(TIERS))]
    if not plans:raise ValueError('Insufficient supplied tier/rarity capacity')
    def rank(value):return hashlib.sha256(f'{SELECTION}:{definition}:{catalog_id}:{value}'.encode()).digest()
    plan=min(plans,key=lambda p:rank('plan:'+','.join(map(str,p))))
    chosen=[];used=set()
    for i,tier in enumerate(TIERS):
        common_needed=counts[tier]-plan[i]
        for rare,number in ((True,plan[i]),(False,common_needed)):
            ordered=sorted(groups[tier,rare],key=lambda p:rank(f'{p.item_family}:{p.resource_id}:{p.special_version_id or "base"}'))
            taken=0
            if not number:continue
            if rates:
                # pack_special_rates_v1: each slot decides special-or-not first.
                def usable(item, picked, tier=tier, rare=rare, common_needed=common_needed):
                    taken_ids = used | {c.resource_id for c in picked}
                    if item.resource_id in taken_ids:
                        return False
                    if not rare:
                        return True
                    return len(resources[tier, False] - (taken_ids | {item.resource_id})) >= common_needed
                seed = f'{definition}:{catalog_id}:{tier}:{int(rare)}'
                picked = pick(ordered, number, chances[tier, rare], seed, usable)
                for item in picked:
                    chosen.append(item)
                    used.add(item.resource_id)
                if len(picked) != number:
                    raise ValueError('Cannot satisfy exact unique-resource tier draw')
                continue
            for item in ordered:
                if item.resource_id in used:continue
                # Preserve sufficient common identities when a common base and
                # one of its rare special versions occupy opposite rarity sets.
                if rare and len(resources[tier,False]-(used|{item.resource_id}))<common_needed:continue
                chosen.append(item);used.add(item.resource_id);taken+=1
                if taken==number:break
            if taken!=number:raise ValueError('Cannot satisfy exact unique-resource tier draw')
    if len(chosen)!=rule['item_count']:raise ValueError('Incomplete exact-tier draw')
    return tuple(sorted(chosen,key=lambda p:rank(f'order:{p.item_family}:{p.resource_id}:{p.special_version_id or "base"}')))

def captions(definition):
    from .store_pool_amendment import previous_definition
    definition=previous_definition(definition)
    p=policy()
    if definition==p['consumer']['definition']:
        from .specialist_consumable_packs import captions as previous
        value=previous(p['consumer']['previous_definition'])
        return {**value,'DESC':value['DESC'].replace('consumables','items')}
    return None

def caption_origin(definition):
    from .store_pool_amendment import previous_definition
    definition=previous_definition(definition)
    return next((r['previous_definition'] for r in policy()['standard_bindings'].values() if r['definition']==definition),definition)
