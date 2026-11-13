"""Explicit isolated match-pack policy. No XP or Store purchase dependency."""
import hashlib,json
from pathlib import Path
PATH=Path(__file__).parent/'policy/native-match-packs.json'
PATH_V2=PATH.with_name('native-match-packs-v2.json')
PATH_V3=PATH.with_name('native-match-packs-v3.json')
PATH_V4=PATH.with_name('native-match-packs-v4.json')
PATH_V5=PATH.with_name('native-match-packs-v5.json')
PATH_V6=PATH.with_name('native-match-packs-v6.json')
STORE_PARITY_PATH=PATH.with_name('reward-store-parity-v1.json')  # Explicit isolated candidate; no normal release admission.
CROWD_FILTERED_PATH=PATH_V6  # Explicit new candidate, never automatic activation.
LATEST_PATH=PATH_V3
CHAMPIONSHIP_PATH=PATH_V4  # Explicit isolated candidate; not the default policy.

def validate_consumable_display_integration(path,*,source_presentation=False,account=None):
    """Only explicit v5/v6 source routing may combine the proven display wire.

    Legacy/default modes retain the existing prohibition. This admits display
    of supplied injury/misc resources, never their effects or source-less grants.
    """
    if type(source_presentation) is not bool:raise ValueError('Explicit source presentation selector required')
    if path is None:return
    from .fresh_account_runtime import selected as fresh_selected
    if fresh_selected(account) and Path(path).resolve() == STORE_PARITY_PATH.resolve():
        return
    from . import reward_release
    if reward_release.ACCOUNT is not None and Path(path).resolve()==STORE_PARITY_PATH.resolve():return
    if not source_presentation or snapshot(9,path)['version'] not in ('native_match_packs_v5','native_match_packs_v6','reward_store_parity_v1'):
        raise ValueError('Combined consumable display/rewards requires isolated v5/v6 source presentation')

def snapshot(division,path=PATH):
    if Path(path).resolve()==STORE_PARITY_PATH.resolve():
        from .reward_store_parity import snapshot as store_snapshot
        return store_snapshot(division)
    from .local_packs import DEFINITIONS
    value=json.loads(Path(path).read_text())
    specials=value.get('version')=='native_match_packs_v2'
    crowd_filtered=value.get('version')=='native_match_packs_v6'
    division9_title=value.get('version') in ('native_match_packs_v5','native_match_packs_v6')
    championship=value.get('version') in ('native_match_packs_v4','native_match_packs_v5','native_match_packs_v6')
    filtered=value.get('version') in ('native_match_packs_v3','native_match_packs_v4','native_match_packs_v5','native_match_packs_v6')
    from .pack_policy import all_tier_special_bindings,filtered_consumable_bindings,crowd_filtered_consumable_bindings
    bindings=crowd_filtered_consumable_bindings() if crowd_filtered else filtered_consumable_bindings() if filtered else all_tier_special_bindings() if specials else {'Bronze':'revival_bronze_mixed_v1','Premium Bronze':'revival_premium_bronze_mixed_v1'}
    expected={'version':'native_match_packs_v6' if crowd_filtered else 'native_match_packs_v5' if division9_title else 'native_match_packs_v4' if championship else 'native_match_packs_v3' if filtered else 'native_match_packs_v2' if specials else 'native_match_packs_v1','classification':'revival_policy','default_enabled':False,
              'bindings':{k:bindings[k] for k in ('Bronze','Premium Bronze')},
              'enabled_divisions':[10,9],'xp_enabled':False,'season_packs_enabled':championship}
    if championship:
        expected['championship_bindings']={'10':bindings['Bronze']}
        if division9_title:expected['championship_bindings']['9']=bindings['Premium Bronze']
        if any(type(value.get(k)) is not bool for k in ('default_enabled','xp_enabled','season_packs_enabled')):raise ValueError('Explicit championship policy switches required')
    if value!=expected:raise ValueError('Unsupported isolated match pack policy')
    if type(division) is not int or division not in value['enabled_divisions']:raise ValueError('Division pack bindings not certified')
    table=json.loads((PATH.parent/'offline-rewards-v1.json').read_text())
    outcomes={}
    for result in 'WDL':
        label=table['divisions'][str(division)]['match'][result]['pack_label']
        definition=value['bindings'][label];rule=DEFINITIONS[definition]
        if rule['item_family']!='mixed_bronze':raise ValueError('No pack substitution')
        outcomes[result]={'label':label,'definition':definition,'definition_sha256':hashlib.sha256((json.dumps(rule,indent=2,sort_keys=True)+'\n').encode()).hexdigest()}
    return {'version':value['version'],'division':division,'policy_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),'outcomes':outcomes}

def championship_definition(division,path):
    """Explicit D10v4 or D10/D9v5/v6 candidate; no other band or cash grant.

    Its independent source snapshot is pinned by the coordinator at CreateSim.
    Existing policies return None and retain their original match-only scope.
    """
    if type(division) is not int or not 1<=division<=10:raise ValueError('Invalid title pack division')
    if Path(path).resolve()==STORE_PARITY_PATH.resolve():
        from .reward_store_parity import snapshot as store_snapshot
        return store_snapshot(division,current=False)['championship']['definition']
    # Recovery of an old final source must still work after a rollover into a
    # division where creating another match with this policy is not admitted.
    # Match creation separately validates its own division in _pack_snapshot.
    quote=snapshot(10,path)
    if quote['version'] not in ('native_match_packs_v4','native_match_packs_v5','native_match_packs_v6'):return None
    return json.loads(Path(path).read_text())['championship_bindings'].get(str(division))

def validate_snapshot(value):
    if type(value) is not dict:raise ValueError('Invalid pinned match pack policy')
    version=value.get('version')
    if version=='reward_store_parity_v1':
        from .reward_store_parity import validate_snapshot as store_validate
        return store_validate(value)
    backend_versions=('backend_approved_match_packs_v1','backend_approved_match_packs_v2','backend_approved_match_packs_v3','backend_approved_match_packs_v4','backend_approved_match_packs_v5')
    if version in backend_versions:
        expected=backend_snapshot(value.get('division'),specials=version!='backend_approved_match_packs_v1',
            expanded_consumables=version in backend_versions[2:],filtered_consumables=version in backend_versions[3:],
            exclude_capacity_crowd=version=='backend_approved_match_packs_v5')
    else:
        expected=snapshot(value.get('division'),PATH_V6 if version=='native_match_packs_v6' else PATH_V5 if version=='native_match_packs_v5' else PATH_V4 if version=='native_match_packs_v4' else PATH_V3 if version=='native_match_packs_v3' else PATH_V2 if version=='native_match_packs_v2' else PATH)
    if value!=expected:raise ValueError('Invalid pinned match pack policy')
    return value

def backend_snapshot(division,*,specials=False,expanded_consumables=False,filtered_consumables=False,exclude_capacity_crowd=False):
    """All approved match tiers, private backend scope; never a CLI policy file.

    The native snapshot(path) remains strictly D10/D9. This prospective snapshot
    reuses the same source/entitlement journal without claiming stock admission.
    """
    from .local_packs import DEFINITIONS
    from .pack_policy import CLASSIC_MIXED_BINDINGS,all_tier_special_bindings,expanded_consumable_bindings,filtered_consumable_bindings,crowd_filtered_consumable_bindings
    from .revival_rewards import load_reward_policy,POLICY
    if type(division) is not int or not 1<=division<=10:raise ValueError('Invalid backend pack division')
    if type(specials) is not bool:raise ValueError('Explicit all-tier special policy required')
    if type(expanded_consumables) is not bool or (expanded_consumables and not specials):raise ValueError('Expanded consumables require explicit prospective all-specials policy')
    if type(filtered_consumables) is not bool or (filtered_consumables and not expanded_consumables):raise ValueError('Filtered consumables require explicit prospective expanded policy')
    if type(exclude_capacity_crowd) is not bool or (exclude_capacity_crowd and not filtered_consumables):raise ValueError('Capacity Crowd exclusion requires explicit filtered policy')
    bindings=crowd_filtered_consumable_bindings() if exclude_capacity_crowd else filtered_consumable_bindings() if filtered_consumables else expanded_consumable_bindings() if expanded_consumables else all_tier_special_bindings() if specials else CLASSIC_MIXED_BINDINGS
    table=load_reward_policy();outcomes={}
    for result in 'WDL':
        label=table['divisions'][str(division)]['match'][result]['pack_label']
        definition=bindings[label];rule=DEFINITIONS[definition]
        if rule['name']!=label+' Pack' or rule['item_family']!='mixed_'+rule['quality']:raise ValueError('Unsupported approved pack definition')
        outcomes[result]={'label':label,'definition':definition,'definition_sha256':hashlib.sha256((json.dumps(rule,indent=2,sort_keys=True)+'\n').encode()).hexdigest()}
    return {'version':'backend_approved_match_packs_v5' if exclude_capacity_crowd else 'backend_approved_match_packs_v4' if filtered_consumables else 'backend_approved_match_packs_v3' if expanded_consumables else 'backend_approved_match_packs_v2' if specials else 'backend_approved_match_packs_v1','classification':'backend_only','division':division,
            'table_sha256':hashlib.sha256(POLICY.read_bytes()).hexdigest(),'outcomes':outcomes}
