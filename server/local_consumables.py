"""Hash-validated supplied consumable references; no copied asset metadata.

Versioned pack/ownership admission includes approved supplied healing/misc rows.
Effect admission remains separate: only proven training families are enabled.
"""
from functools import lru_cache
from .local_content_source import DB,META,cards
from scripts.local_football_db import FootballDB
RULES={133:('formation_id',25),51:('training_resource',None),78:('formation_id',15)}
LEGACY_POOL='training_v1'
EXPANDED_POOL='training_injury_misc_v1'
FILTERED_POOL='training_injury_misc_filtered_v1'
CROWD_FILTERED_POOL='training_injury_misc_filtered_v2'
CURRENT_POOL=CROWD_FILTERED_POOL
INJURY_SUBTYPES=frozenset((211,212,213,215,216,217,218))
@lru_cache(maxsize=1)
def inventory_references():
    """All valid supplied consumables for ownership; effect admission is separate."""
    cards();db=FootballDB(DB,META);limit=db.table('fcc_trainingcards')['valid_count']
    return {r['carddbid']:r for r in db.rows('fcc_trainingcards',
        ['carddbid','cardsubtype','rating','cardassetid','amount','weightrare'])
        if r['row_index']<limit}

def inventory_reference(resource_id):
    """Ownership admission is separate from pool versions and native effects."""
    refs=pack_references(EXPANDED_POOL)
    if type(resource_id) is not int or resource_id not in refs:raise ValueError('Unknown supplied consumable')
    return refs[resource_id]

@lru_cache(maxsize=5)
def pack_references(pool=LEGACY_POOL):
    """Immutable pools: legacy153, expanded195, filtered136, Crowd-filtered135.

    Injury healing alone is admitted from the healing table. Fitness/morale and
    contracts are excluded. No coin/free-pack/crowd effect is enabled by owning
    a miscellaneous item; supplied amounts are never applied automatically.
    """
    if pool=='training_injury_misc_no_crowd_v3':
        from .store_pool_amendment import policy
        excluded=policy()['excluded_subtypes']
        return {rid:r for rid,r in pack_references(CROWD_FILTERED_POOL).items() if r['cardsubtype'] not in excluded}
    if pool==LEGACY_POOL:return inventory_references()
    if pool==CROWD_FILTERED_POOL:
        import json
        from pathlib import Path
        policy=json.loads((Path(__file__).parent/'policy/consumable-pool-exclusions-v2.json').read_text())
        expected={'version':'consumable_pool_exclusions_v2','classification':'revival_policy',
                  'base_pool':FILTERED_POOL,'pool':CROWD_FILTERED_POOL,
                  'excluded_resource_ids':[5004012]}
        if policy!=expected:raise ValueError('Invalid Capacity Crowd exclusion policy')
        return {rid:row for rid,row in pack_references(FILTERED_POOL).items()
                if rid not in policy['excluded_resource_ids']}
    if pool==FILTERED_POOL:
        import json
        from pathlib import Path
        policy=json.loads((Path(__file__).parent/'policy/consumable-pool-exclusions-v1.json').read_text())
        expected={'version':'consumable_pool_exclusions_v1','classification':'revival_policy',
                  'base_pool':EXPANDED_POOL,'pool':FILTERED_POOL,
                  'excluded_subtype_ranges':[[250,273],[300,334]]}
        if policy!=expected:raise ValueError('Invalid versioned consumable exclusions')
        return {rid:row for rid,row in pack_references(EXPANDED_POOL).items()
                if not any(lo<=row['cardsubtype']<=hi for lo,hi in policy['excluded_subtype_ranges'])}
    if pool!=EXPANDED_POOL:raise ValueError('Unknown consumable pool version')
    result=dict(inventory_references());db=FootballDB(DB,META)
    for table,subtypes in (('fcc_healingcards',INJURY_SUBTYPES),('fcc_misccards',frozenset((231,232,233)))):
        limit=db.table(table)['valid_count']
        for row in db.rows(table,['carddbid','cardsubtype','rating','cardassetid','amount','weightrare']):
            if row['row_index']>=limit or row['cardsubtype'] not in subtypes:continue
            if row['carddbid'] in result:raise ValueError('Conflicting supplied consumable identity')
            result[row['carddbid']]=row
    return result

#01026a50 case0x85→nested+80=25/f451. Subtype51 supplies a stat0
#training amount; player enrichment01028098 reads training+58 as DB resource.
@lru_cache(maxsize=1)
def references():
    # Preserve historical definitions which use this admitted legacy table.
    # New mappings do not silently expand their draws or enabled effects.
    return {rid:r for rid,r in inventory_references().items() if r['cardsubtype'] in RULES}
def reference(resource_id):
    if type(resource_id) is not int or resource_id not in references():raise ValueError('Unmapped supplied consumable resource')
    return references()[resource_id]
def effect(resource_id):
    subtype=reference(resource_id)['cardsubtype']
    field,value=RULES[subtype]
    return field,resource_id if field=='training_resource' else value

def mapped_reference(resource_id):
    from .consumable_effects import MAPPED_SUBTYPES
    row=inventory_reference(resource_id)
    if row['cardsubtype'] not in MAPPED_SUBTYPES:raise ValueError('Unmapped supplied consumable resource')
    return row

def mapped_effect(resource_id):
    from .consumable_effects import PLAYER_FORMATIONS,MANAGER_FORMATIONS,TRAINING_SUBTYPES
    subtype=mapped_reference(resource_id)['cardsubtype']
    if subtype in PLAYER_FORMATIONS:return 'formation_id',PLAYER_FORMATIONS[subtype]
    if subtype in MANAGER_FORMATIONS:return 'formation_id',MANAGER_FORMATIONS[subtype]
    if subtype in TRAINING_SUBTYPES:return 'training_resource',resource_id
    raise ValueError('Position effect requires its current source position')

def validate_training_target(resource_id,player_resource_id):
    """Run314 GK training51; native enrichment uses one resource at +58."""
    from .local_content_source import position_for
    from .consumable_effects import TRAINING_SUBTYPES
    subtype=mapped_reference(resource_id)['cardsubtype']
    if subtype not in TRAINING_SUBTYPES or (position_for(player_resource_id)=='GK')!=(subtype<60):
        raise ValueError('Unsupported/incompatible consumable target')
