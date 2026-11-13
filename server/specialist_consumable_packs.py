"""Approved consumable-only draws; Store/UI admission is a separate milestone."""
import hashlib
import itertools
import json
from pathlib import Path
from .local_consumables import CROWD_FILTERED_POOL,pack_references
from .policy_memo import policy_memo

PATH=Path(__file__).parent/'policy/specialist-consumable-packs-v1.json'
SELECTION='consumables_tier_quota_v1'
TIERS=('bronze','silver','gold')

def policy():
    value=json.loads(PATH.read_bytes())
    if (value['version']!='specialist_consumable_packs_v1' or value['classification']!='revival_policy' or
        value['default_enabled'] is not False or value['stock_delivery_enabled'] is not False or
        value['consumable_pool']!=CROWD_FILTERED_POOL or value['fifa_points_enabled'] is not False):
        raise ValueError('Uncertified specialist Store policy')
    return value

def quality(row):return 'gold' if row['rating']>=75 else 'silver' if row['rating']>=65 else 'bronze'

def pool(scope):
    rows=pack_references(CROWD_FILTERED_POOL)
    if scope=='all':return rows
    if scope not in ('player_formation','player_position'):raise ValueError('Unsupported specialist pool')
    low,high=(71,86) if scope=='player_formation' else (91,110)
    return {rid:r for rid,r in rows.items() if low<=r['cardsubtype']<=high}

def validate_definition(key,rule):
    p=policy();source=p['pack_definitions'].get(key)
    if source is None:raise ValueError('Unapproved specialist definition')
    expected={'provenance':'revival_policy','name':source['name'],'item_family':'consumable',
        'quality':'mixed' if source['scope']=='all' else 'gold','item_count':12,
        'minimum_rare':source['rare_count'],'exact_rare':True,'tier_counts':source['tier_counts'],
        'consumable_scope':source['scope'],'consumable_pool':p['consumable_pool'],
        'selection':SELECTION,'weights':{'common':1,'rare':1}}
    counts=source['tier_counts']
    if (rule!=expected or any(type(rule[k]) is not type(v) for k,v in expected.items()) or
        type(source['coin_price']) is not int or source['coin_price']<=0 or
        type(source['rare_count']) is not int or not 0<=source['rare_count']<=12 or
        type(counts) is not dict or set(counts)!=set(TIERS) or
        any(type(n) is not int or not 0<=n<=12 for n in counts.values()) or sum(counts.values())!=12):
        raise ValueError('Specialist pack guarantee/policy mismatch')
    return rule

def select_resources(definition,catalog_id,rule,*,private_identity_version=None):
    validate_definition(definition,rule)
    if private_identity_version not in (None,'private_pack_identity_v2'):raise ValueError('Unknown private identity version')
    limit=0x7ffffffffffffffe if private_identity_version=='private_pack_identity_v2' else 65535
    if type(catalog_id) is not int or not 30001<=catalog_id<=limit:raise ValueError('Full entitlement identity required')
    rows=pool(rule['consumable_scope']);counts=rule['tier_counts']
    groups={(tier,rare):[rid for rid,row in rows.items() if quality(row)==tier and bool(row['weightrare'])==rare]
            for tier in TIERS for rare in (False,True)}
    # Pick a feasible rarity distribution first, then unique references within
    # each tier/rarity group. No fake card tiers and no seed retry loop.
    plans=[plan for plan in itertools.product(*(range(counts[t]+1) for t in TIERS))
        if sum(plan)==rule['minimum_rare'] and all(
            plan[n]<=len(groups[t,True]) and counts[t]-plan[n]<=len(groups[t,False])
            for n,t in enumerate(TIERS))]
    if not plans:raise ValueError('Insufficient supported specialist pool for guarantees')
    def rank(identity):return hashlib.sha256(f'{SELECTION}:{definition}:{catalog_id}:{identity}'.encode()).digest()
    chosen=[];plan=min(plans,key=lambda p:rank('rarity-plan:'+','.join(map(str,p))))
    for n,t in enumerate(TIERS):
        for rare,number in ((True,plan[n]),(False,counts[t]-plan[n])):
            chosen.extend(sorted(groups[t,rare],key=lambda rid:rank('resource:'+str(rid)))[:number])
    if len(chosen)!=12 or len(set(chosen))!=12:raise ValueError('Incomplete specialist draw')
    return tuple(sorted(chosen,key=lambda rid:rank('order:'+str(rid))))

DEFINITIONS=('revival_consumables_balanced_v1','revival_player_formations_v1','revival_player_positions_v1')

def category_ids(definition):
    """Original group501 children: index6→516 / index7→517 (capture755)."""
    scope=policy()['pack_definitions'][definition]['scope']
    return {'all':[],'player_formation':[517],'player_position':[516]}[scope]

@policy_memo
def catalog():
    """Preserve all twelve v2 products/FP choices; append three coin-only SKUs."""
    from .store_fp_policy import catalog as previous
    result=previous();result['version']='local_store_catalog_v3'
    for n,(definition,row) in enumerate(policy()['pack_definitions'].items()):
        result['products'].append({'product_id':58001+n,'definition':definition,'provenance':'revival_policy',
            'coin_price':row['coin_price'],'repeatable':True,'purchase_limit':1,'featured':row['scope']=='all'})
    return result

def captions(definition):
    """Plain user-defined composition text, never labeled recovered EA copy."""
    if definition not in DEFINITIONS:return None
    row=policy()['pack_definitions'][definition];counts=row['tier_counts']
    items='4 Gold, 4 Silver and 4 Bronze consumables' if row['scope']=='all' else '12 Gold player formation items' if row['scope']=='player_formation' else '12 Gold player position items'
    return {'NAME':row['name'],'DESC':f"{items}. {row['rare_count']} Rares. Fitness and morale items excluded.",
            'SHORT':f"12 ITEMS\n{counts['gold']} GOLD\n{row['rare_count']} RARES"}
