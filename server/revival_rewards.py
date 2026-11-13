"""Pure approved revival reward/catalog quotes; no account mutation or wire reply.

Policy labels are deliberately distinct from admitted PackStore definition keys.
An unsupported product or unresolved season pack cannot be converted to a grant.
"""
import copy
import json
from pathlib import Path
from .account_progression import load_progression_policy,quote
from .local_profile import validate_credits
from .season_revival_policy import load_policy,LEVELS

POLICY=Path(__file__).parent/'policy/offline-rewards-v1.json'
LABELS=('Bronze','Premium Bronze','Silver','Premium Silver','Gold','Premium Gold',
        'Jumbo Premium Gold','Premium Gold Players','Mega','Rare Players','Jumbo Rare Players','Ultimate')
PRICES=(400,750,2500,3750,5000,7500,15000,25000,35000,50000,100000,125000)
MATCH_PACKS=(('Premium Bronze','Bronze','Bronze'),)*2+(('Silver','Premium Bronze','Bronze'),)*2+(
    ('Premium Silver','Silver','Premium Bronze'),)*2+(('Gold','Premium Silver','Silver'),)*2+(
    ('Premium Gold','Gold','Premium Silver'),)*2
TITLE_PACKS=LABELS[:10]
# Already15x existing authorization table, in RELEGATION/MAINTENANCE/PROMOTION/TITLE order.
SEASON_COINS=((None,4500,22500,28500),(3750,6000,27000,34500),
              (4500,7500,31500,40500),(5250,9000,37500,48000),
              (6750,11250,43500,57000),(8250,13500,51000,67500),
              (9750,16500,60000,78000),(12000,20250,70500,91500),
              (14250,24000,82500,108000),(18000,30000,None,135000))
COINS=((2250,1350,750),(2700,1575,900),(3150,1875,1050),(3750,2250,1275),
       (4500,2700,1500),(5400,3225,1800),(6450,3825,2175),(7650,4575,2550),
       (9000,5400,3000),(10500,6300,3525))

def load_reward_policy(path=POLICY):
    value=json.loads(Path(path).read_text())
    required={'classification','version','default_enabled','stock_delivery_enabled','coin_tables_are_already_15x',
              'progression_policy_version','season_source_policy_version','season_coin_factor','divisions',
              'permanent_coin_catalog','rationale'}
    fixed={'classification':'revival_policy','version':'offline_rewards_v1','default_enabled':False,
           'stock_delivery_enabled':False,'coin_tables_are_already_15x':True,
           'progression_policy_version':'account_progression_v1',
           'season_source_policy_version':'existing_xp_authorization_table_15x_v1','season_coin_factor':1}
    if type(value) is not dict or set(value)!=required:raise ValueError('Invalid reward policy schema')
    for key,expected in fixed.items():
        if type(value[key]) is not type(expected) or value[key]!=expected:raise ValueError('Unsupported reward policy activation/version')
    if not isinstance(value['rationale'],str) or not value['rationale']:raise ValueError('Missing revival rationale')
    rows=value['divisions'];progression=load_progression_policy()
    if type(rows) is not dict or set(rows)!={str(i) for i in range(1,11)}:raise ValueError('Ten explicit reward divisions required')
    for d in range(10,0,-1):
        row=rows[str(d)]
        if type(row) is not dict or set(row)!={'match','season'}:raise ValueError('Invalid division reward schema')
        if type(row['match']) is not dict or set(row['match'])!=set('WDL'):raise ValueError('Explicit result rewards required')
        for result,coins,label in zip('WDL',COINS[10-d],MATCH_PACKS[10-d]):
            entry=row['match'][result]
            if type(entry) is not dict or set(entry)!={'level1_coins','pack_label'}:raise ValueError('Invalid match reward')
            validate_credits(entry['level1_coins'])
            if entry['level1_coins']!=coins or entry['pack_label']!=label or quote(progression,d,result,0)['coins']!=coins:
                raise ValueError('Approved match reward table mismatch')
        if type(row['season']) is not dict or set(row['season'])!=set(LEVELS):raise ValueError('Explicit season bands required')
        for band,base in zip(LEVELS,SEASON_COINS[10-d]):
            entry=row['season'][band];expected=base
            if type(entry) is not dict or set(entry)!={'coins','pack_label','pack_status'}:raise ValueError('Invalid season reward')
            if entry['coins'] is not None:validate_credits(entry['coins'])
            if entry['coins']!=expected:raise ValueError('Existing15x season table mismatch')
            label=TITLE_PACKS[10-d] if band=='CHAMPIONSHIP' else None
            status='authorized' if band=='CHAMPIONSHIP' else 'inapplicable' if base is None else 'unresolved'
            if entry['pack_label']!=label or entry['pack_status']!=status:raise ValueError('Unapproved season pack tier')
    catalog=value['permanent_coin_catalog']
    if type(catalog) is not dict or set(catalog)!=set(LABELS):raise ValueError('Twelve explicit permanent packs required')
    for label,price in zip(LABELS,PRICES):
        entry=catalog[label]
        if type(entry) is not dict or set(entry)!={'coin_price','definition','availability'}:raise ValueError('Invalid permanent coin product')
        validate_credits(entry['coin_price'])
        if entry!={'coin_price':price,'definition':None,'availability':'unsupported_pending_evidence'}:
            raise ValueError('Unsupported price/resource binding; new evidence and version required')
    return value

def match_quote(division,result,start_total_xp,policy=None):
    policy=policy or load_reward_policy()
    calculation=quote(load_progression_policy(),division,result,start_total_xp)
    row=policy['divisions'][str(division)]['match'][result]
    # Only match coins get the pre-fixture level factor;15x is already in row.
    if calculation['coins']!=row['level1_coins']*calculation['coin_multiplier_numerator']//50:
        raise ValueError('Progression/reward policy mismatch')
    return {**calculation,'reward_policy_version':policy['version'],'pack_label':row['pack_label'],
            'pack_definition':None,'stock_delivery_enabled':False,'pack_delivery_enabled':False}

def match_coin_quote(division,result,start_total_xp):
    """Read only approved coin rows; XP, pack/catalog admission is independent.

    The table already contains15x. Account XP is read solely to derive the level
    snapshotted at creation; this quote does not award or project any XP.
    """
    import hashlib
    from .account_progression import level_state
    value=json.loads(POLICY.read_text())
    if (value.get('classification')!='revival_policy' or value.get('version')!='offline_rewards_v1' or
        value.get('coin_tables_are_already_15x') is not True):raise ValueError('Unsupported match coin table')
    rows={}
    for d in range(10,0,-1):
        row={outcome:value['divisions'][str(d)]['match'][outcome]['level1_coins'] for outcome in 'WDL'}
        for outcome,expected in zip('WDL',COINS[10-d]):
            if type(row[outcome]) is not int or row[outcome]!=expected:raise ValueError('Approved15x coin table mismatch')
        rows[str(d)]=row
    if type(division) is not int or not 1<=division<=10 or result not in ('W','D','L'):
        raise ValueError('Invalid coin division/result')
    start=level_state(start_total_xp);base=rows[str(division)][result]
    amount=validate_credits(base*(50+start['level']-1)//50)
    return {'policy_version':'native_match_coins_v1','classification':'revival_policy',
            'table_version':value['version'],'table_sha256':hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'division':division,'result':result,'start_total_xp':start_total_xp,'start_level':start['level'],
            'level1_coins_already_15x':base,'level_multiplier_numerator':50+start['level']-1,
            'level_multiplier_denominator':50,'amount':amount}

def season_quote(division,band,policy=None):
    policy=policy or load_reward_policy()
    if type(division) is not int or not 1<=division<=10 or band not in LEVELS:raise ValueError('Invalid season quote')
    row=copy.deepcopy(policy['divisions'][str(division)]['season'][band])
    if row['coins'] is None:raise ValueError('Inapplicable season band')
    return {**row,'classification':'revival_policy','reward_policy_version':policy['version'],
            'division':division,'band':band,'pack_definition':None,'delivery_enabled':False}

def permanent_catalog(policy=None):
    policy=policy or load_reward_policy()
    return copy.deepcopy(policy['permanent_coin_catalog'])
