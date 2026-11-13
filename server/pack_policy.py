"""Versioned revival definitions; protocol and account state hold only references."""
import json
from pathlib import Path
from .policy_memo import policy_memo
PATH=Path(__file__).parent/'policy/pack-definitions.json'
CLASSIC_MIXED_BINDINGS={
    'Bronze':'revival_bronze_mixed_v1',
    'Premium Bronze':'revival_premium_bronze_mixed_v1',
    'Silver':'revival_silver_mixed_v1',
    'Premium Silver':'revival_premium_silver_mixed_v1',
    'Gold':'revival_gold_mixed_v1',
    'Premium Gold':'revival_premium_gold_mixed_v1',
}

@policy_memo
def all_tier_special_bindings():
    """Prospective release bindings only; old snapshots and definitions persist."""
    value=json.loads(PATH.with_name('all-tier-special-pack-bindings-v1.json').read_text())
    if (set(value)!={'version','classification','default_enabled','tier_basis','bindings'} or
        value['version']!='all_tier_special_pack_bindings_v1' or value['classification']!='revival_policy' or
        value['default_enabled'] is not False or value['tier_basis']!='preserved_base_quality' or len(value['bindings'])!=12):raise ValueError('Invalid all-tier special policy')
    definitions=load_definitions();result={}
    for label,row in value['bindings'].items():
        if set(row)!={'previous_definition','definition'} or row['definition']==row['previous_definition']:raise ValueError('Immutable new pack version required')
        old,new=(definitions[row[k]] for k in ('previous_definition','definition'))
        for key in ('name','quality','item_count','minimum_rare','new_player_fitness','new_player_formation'):
            if old[key]!=new[key]:raise ValueError('Special admission cannot alter pack guarantees')
        if new.get('special_pool')!='reviewed_all_admitted' or new.get('specials_satisfy_rare_guarantee') is not True:raise ValueError('All admitted same-tier specials required')
        result[label]=row['definition']
    return result

@policy_memo
def expanded_consumable_bindings():
    """New mixed definitions only; old sources, prices and draws are immutable."""
    value=json.loads(PATH.with_name('expanded-consumable-pack-bindings-v1.json').read_text())
    from .local_consumables import EXPANDED_POOL
    if (set(value)!={'version','classification','default_enabled','stock_delivery_enabled','bindings'} or
        value['version']!='expanded_consumable_pack_bindings_v1' or value['classification']!='revival_policy' or
        value['default_enabled'] is not False or value['stock_delivery_enabled'] is not False):raise ValueError('Invalid expanded consumable bindings')
    previous=all_tier_special_bindings();definitions=load_definitions()
    if set(value['bindings'])!=set(previous):raise ValueError('Complete catalog binding required')
    result={}
    for label,row in value['bindings'].items():
        if set(row)!={'previous_definition','definition'} or row['previous_definition']!=previous[label]:raise ValueError('Immutable previous catalog required')
        old,new=(definitions[row[k]] for k in ('previous_definition','definition'))
        mixed=old.get('item_family','player').startswith('mixed_')
        if mixed:
            if row['definition']==row['previous_definition'] or new!={**old,'consumable_pool':EXPANDED_POOL}:raise ValueError('Only consumable pool expansion is approved')
        elif row['definition']!=row['previous_definition'] or new!=old:raise ValueError('Player-only packs must remain unchanged')
        result[label]=row['definition']
    return result

@policy_memo
def filtered_consumable_bindings():
    """Frozen v1 range exclusions; retain these definitions for pinned receipts."""
    value=json.loads(PATH.with_name('filtered-consumable-pack-bindings-v1.json').read_text())
    from .local_consumables import FILTERED_POOL
    if (set(value)!={'version','classification','default_enabled','stock_delivery_enabled','bindings'} or
        value['version']!='filtered_consumable_pack_bindings_v1' or value['classification']!='revival_policy' or
        value['default_enabled'] is not False or value['stock_delivery_enabled'] is not False):raise ValueError('Invalid filtered consumable bindings')
    previous=expanded_consumable_bindings();definitions=load_definitions()
    if set(value['bindings'])!=set(previous):raise ValueError('Complete filtered catalog required')
    result={}
    for label,row in value['bindings'].items():
        if set(row)!={'previous_definition','definition'} or row['previous_definition']!=previous[label]:raise ValueError('Immutable previous catalog required')
        old,new=(definitions[row[k]] for k in ('previous_definition','definition'))
        if old.get('item_family','player').startswith('mixed_'):
            if row['definition']==row['previous_definition'] or new!={**old,'consumable_pool':FILTERED_POOL}:raise ValueError('Only approved consumable exclusions may change')
        elif row['definition']!=row['previous_definition'] or new!=old:raise ValueError('Player-only packs must remain unchanged')
        result[label]=row['definition']
    return result

@policy_memo
def crowd_filtered_consumable_bindings():
    """Prospective user-approved Capacity Crowd exclusion; never rewrite v4."""
    value=json.loads(PATH.with_name('filtered-consumable-pack-bindings-v2.json').read_text())
    from .local_consumables import CROWD_FILTERED_POOL
    expected={'version':'filtered_consumable_pack_bindings_v2','classification':'revival_policy',
              'default_enabled':False,'stock_delivery_enabled':False}
    if set(value)!=set(expected)|{'bindings'} or any(type(value[k]) is not type(v) or value[k]!=v for k,v in expected.items()):
        raise ValueError('Invalid Capacity Crowd pack bindings')
    previous=filtered_consumable_bindings();definitions=load_definitions()
    if type(value['bindings']) is not dict or set(value['bindings'])!=set(previous):raise ValueError('Complete prospective catalog required')
    result={}
    for label,row in value['bindings'].items():
        if type(row) is not dict or set(row)!={'previous_definition','definition'} or row['previous_definition']!=previous[label]:
            raise ValueError('Immutable previous catalog required')
        old,new=(definitions[row[k]] for k in ('previous_definition','definition'))
        if old.get('item_family','player').startswith('mixed_'):
            if row['definition']==row['previous_definition'] or new!={**old,'consumable_pool':CROWD_FILTERED_POOL}:
                raise ValueError('Only approved Capacity Crowd exclusion may change')
        elif row['definition']!=row['previous_definition'] or new!=old:raise ValueError('Player-only packs must remain unchanged')
        result[label]=row['definition']
    return result

_DEFINITIONS_CACHE={}


def load_definitions(path=PATH):
    #PERF: pure validation of exact policy bytes; deep copy per caller.
    import copy,hashlib
    raw=Path(path).read_bytes();key=(str(Path(path).resolve()),hashlib.sha256(raw).digest())
    hit=_DEFINITIONS_CACHE.get(key)
    if hit is None:
        hit=_load_definitions(raw)
        if len(_DEFINITIONS_CACHE)>=8:_DEFINITIONS_CACHE.clear()
        _DEFINITIONS_CACHE[key]=hit
    return copy.deepcopy(hit)


def _load_definitions(raw):
    value=json.loads(raw.decode())
    if set(value)!={'schema_version','provenance','definitions'} or type(value['schema_version']) is not int or value['schema_version']!=1 or value['provenance']!='revival_policy':
        raise ValueError('Invalid pack policy')
    definitions=value['definitions']
    if type(definitions) is not dict or not definitions:raise ValueError('Empty pack policy')
    for key,r in definitions.items():
        if not isinstance(key,str) or not key.startswith('revival_') or type(r) is not dict or r.get('provenance')!='revival_policy':raise ValueError('Invalid definition provenance')
        family=r.get('item_family','player')
        if r.get('selection') == 'specific_supplied_consumable_v1':
            from .store_single_consumables import validate_definition
            validate_definition(key, r)
            continue
        if r.get('selection') == 'reviewed_tier_special_v1':
            from .tournament_special_packs import validate_definition
            validate_definition(key, r)
            continue
        if r.get('selection')=='typed_tier_quota_v1':
            from .standard_pack_specs import validate_definition
            validate_definition(key,r,definitions)
            continue
        if r.get('selection')=='consumables_tier_quota_v1':
            from .specialist_consumable_packs import validate_definition
            validate_definition(key,r)
            continue
        if family in ('mixed_bronze','mixed_silver','mixed_gold'):
            tier=family.removeprefix('mixed_');minimum='minimum_'+tier
            tier_specials=r.get('selection')==f'mixed_{tier}_all_specials_v1'
            required={'provenance','name','quality','item_family','item_count','minimum_rare',
                      'exact_rare',minimum,'selection','weights','new_player_fitness',
                      'new_player_formation','unopened_priority','is_premium'}
            if tier=='gold' or tier_specials:required|={'special_pool','specials_satisfy_rare_guarantee'}
            if 'consumable_pool' in r:
                from .local_consumables import EXPANDED_POOL,FILTERED_POOL,CROWD_FILTERED_POOL
                if r['consumable_pool'] not in (EXPANDED_POOL,FILTERED_POOL,CROWD_FILTERED_POOL) or not tier_specials:raise ValueError('Invalid prospective consumable pool')
                required.add('consumable_pool')
            if 'club_item_pool' in r:
                from .local_club_items import POOL
                if r['club_item_pool']!=POOL or not tier_specials or 'consumable_pool' not in r:
                    raise ValueError('Invalid prospective club-item pool')
                required.add('club_item_pool')
            large = tier=='gold' and (r.get('selection')=='mixed_gold_random_v2' or (tier_specials and r.get('item_count') in (24,30)))
            shape = (r.get('item_count'),r.get(minimum),r.get('minimum_rare'))
            shape_valid = shape in ((24,20,7),(30,26,18)) if large else shape in ((12,10,1),(12,10,3))
            if (set(r)!=required or r['quality']!=tier or type(r['item_count']) is not int or not shape_valid or
                type(r['minimum_rare']) is not int or
                r['exact_rare'] is not True or type(r[minimum]) is not int or
                r['selection']!=(f'mixed_{tier}_all_specials_v1' if tier_specials else 'mixed_gold_random_v2' if large else f'mixed_{tier}_random_v1') or r['weights']!={'common':1,'rare':1} or
                type(r['is_premium']) is not bool or r['is_premium']!=(large or r['minimum_rare']==3) or
                type(r['new_player_fitness']) is not int or r['new_player_fitness']!=99 or r['new_player_formation']!='seeded_random_supported' or
                type(r['unopened_priority']) is not int or r['unopened_priority']!=-100 or not isinstance(r['name'],str) or not r['name']):
                raise ValueError('Invalid mixed tier policy')
            if (tier=='gold' or tier_specials) and (r['special_pool']!='reviewed_all_admitted' or r['specials_satisfy_rare_guarantee'] is not True):raise ValueError('Mixed special policy must preserve admitted pool/rarity')
            continue
        required={'provenance','name','quality','item_count','minimum_rare','selection','weights'}
        required|={'subtypes'} if family=='consumable' else {'new_player_fitness','new_player_formation'}
        if r.get('selection')=='reconstructed_special_test':required|={'special_versions'}
        if r.get('selection')=='reviewed_specials_sha256_without_replacement':required|={'special_pool','special_weight','minimum_special','unopened_priority'}
        optional={'item_family','specials_satisfy_rare_guarantee','guaranteed_special_family','exact_rare','nationality'}
        # STORE-006 (user 6 Nov 2026): a reviewed player pack may draw only one supplied nationality.
        if 'nationality' in r and (type(r['nationality']) is not int or not 1<=r['nationality']<=500 or family!='player'
                or r.get('selection')!='reviewed_specials_sha256_without_replacement'):
            raise ValueError('Nationality filter requires a reviewed player selection')
        if 'exact_rare' in r and (r['exact_rare'] is not True or family!='player' or r.get('selection') not in ('weighted_sha256_without_replacement','reviewed_specials_sha256_without_replacement')):
            raise ValueError('Exact player rarity requires an explicit supported immutable selection')
        if not required<=set(r) or set(r)-required-optional:raise ValueError('Unknown/missing pack policy fields')
        if set(r)&{'specials_satisfy_rare_guarantee','guaranteed_special_family'}:
            if (family!='player' or r['quality']!='gold' or r.get('selection')!='reviewed_specials_sha256_without_replacement'
                or r.get('special_pool')!='reviewed_all_admitted'):raise ValueError('Unsupported Gold special guarantee policy')
            if 'specials_satisfy_rare_guarantee' in r and type(r['specials_satisfy_rare_guarantee']) is not bool:raise ValueError('Invalid special rarity guarantee')
            if 'guaranteed_special_family' in r and (r['guaranteed_special_family'] not in ('totw','tots') or r.get('minimum_special',0)<1):raise ValueError('Invalid special family guarantee')
        if family not in ('player','consumable') or r['quality'] not in ('gold','mixed'):raise ValueError('Unsupported pack pool')
        if type(r['item_count']) is not int or not 1<=r['item_count']<=30 or type(r['minimum_rare']) is not int or not 0<=r['minimum_rare']<=r['item_count']:
            raise ValueError('Invalid pack guarantee')
        if not isinstance(r['name'],str) or not r['name']:raise ValueError('Missing policy name')
        if r['selection'] in ('weighted_sha256_without_replacement','reviewed_specials_sha256_without_replacement'):
            if type(r['weights']) is not dict or set(r['weights'])!={'common','rare'} or any(type(w) is not int or not 1<=w<=100 for w in r['weights'].values()):raise ValueError('Invalid selection weights')
            if r['selection']=='reviewed_specials_sha256_without_replacement':
                if (family!='player' or r['special_pool'] not in ('reviewed_totw3','reviewed_tots11','reviewed_all_admitted') or type(r['special_weight']) is not int
                    or not 1<=r['special_weight']<=100 or type(r['minimum_special']) is not int
                    or not 0<=r['minimum_special']<=r['item_count'] or type(r['unopened_priority']) is not int
                    or not -100<=r['unopened_priority']<=100):raise ValueError('Invalid reviewed special policy')
        elif r['selection']=='reconstructed_special_test':
            if family!='player' or type(r['special_versions']) is not list or len(r['special_versions'])!=r['item_count'] or len(set(r['special_versions']))!=len(r['special_versions']) or not isinstance(r['weights'],str):raise ValueError('Invalid isolated special pack')
        elif r['selection'] not in ('weighted_sha256_without_replacement','SHA256 rank by catalog_id + full resource; one rare then11 independent candidates','Lowest valid supplied resource per proven subtype: GK training and manager formation') or not isinstance(r['weights'],str):raise ValueError('Invalid legacy selection policy')
        if family=='player':
            mixed_reviewed=(r['quality']=='mixed' and r['selection']=='reviewed_specials_sha256_without_replacement'
                            and r['special_pool']=='reviewed_all_admitted')
            if (r['quality']!='gold' and not mixed_reviewed) or r.get('new_player_fitness')!=99 or r.get('new_player_formation')!='seeded_random_supported':raise ValueError('Unsupported player defaults')
        elif type(r.get('subtypes')) is not list or not r['subtypes'] or any(type(x) is not int or x not in (51,133) for x in r['subtypes']):raise ValueError('Unsupported consumable family')
    return definitions
