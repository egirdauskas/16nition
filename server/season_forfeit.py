"""Original season reset, backed by the existing native season recovery journal.

Abandonment is not a match result or a normal season completion. Preserve all
earned receipts and let the original client supply the next selected anchor.
"""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import re
import uuid

from .game_auth import SID
from .native_season_completion import encode, digest

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT/'server/policy/season-forfeit-v1.json'
VERSION = 'season_forfeit_v1'
PENDING = 'native_pending_season_forfeit_v1'
LEGACY_SELECTION = 'legacy_forfeit_selection'
ACCOUNT = None


def policy():
    value = json.loads(POLICY.read_bytes())
    expected = dict(version=VERSION, classification='revival_policy', default_enabled=False,
        outcome='current_points_against_maintenance_threshold', division_floor=10,
        promotion=False, new_coins=0, new_xp=0, new_packs=0, earned_rewards='preserve',
        active_match='refuse', next_season='genuine_original_competition_selection',
        authorization='User29October2026: Yes, current points decide; no new rewards')
    if encode(value) != encode(expected):
        raise ValueError('Unapproved season forfeiture policy')
    return value


def configure(account=None):
    global ACCOUNT
    ACCOUNT = None
    if account is None:
        return
    account = Path(account).resolve()
    from . import season_forfeit_release as release
    from .fresh_account_runtime import selected as fresh_selected
    if account==release.REAL:
        try:release.validate(account)
        except (OSError,ValueError,KeyError,TypeError) as error:
            raise ValueError('Uncertified normal season forfeiture refused') from error
    elif not fresh_selected(account) and (ROOT/'reports' not in account.parents or account.name != 'isolated-account'):
        raise ValueError('Uncertified season forfeiture is isolated-only')
    from .season_choice_release import selected as choices_selected
    if not choices_selected(account):
        raise ValueError('Forfeiture requires existing certified choice/reward composition')
    policy()
    ACCOUNT = account


def selected(account):
    return ACCOUNT is not None and ACCOUNT == Path(account).resolve()


def reset_path(target):
    return re.fullmatch(r'/ut/game/fifaworldmobile/season/([1-9][0-9]*)/division/([1-9][0-9]*)/reset', target)


def record_id(account_id, cycle_id):
    return str(uuid.uuid5(uuid.UUID(account_id), 'season-forfeit:'+cycle_id))


def outcome(division, points, maintenance):
    if (type(division) is not int or not 1 <= division <= 10 or type(points) is not int
            or not 0 <= points <= 30 or type(maintenance) is not int or not 0 <= maintenance <= 30):
        raise ValueError('Invalid forfeiture standings/threshold')
    return min(10, division+1) if points < maintenance else division


def definition_reference(definition):
    from .season_choice_reference import snapshot
    return snapshot(definition) or dict(version='native_forfeit_definition_v1',
        definition_sha256=digest(encode(asdict(definition))))


def legacy_catalog_alias(row,version='native_forfeit_catalog_alias_v2'):
    """Reuse a retained legacy ID instead of leaving an unselectable cache row.

    GetSeasonsIDs0100c640 keeps provider records by division without expiry
    filtering. Only new legacy-retention resets opt into this stable binding;
    existing forfeitures and selected seasons retain their original identities.
    """
    if (row['definition_reference'].get('version')!='native_forfeit_definition_v1'
            or row['division_before']!=row['division_after']):
        return None
    from .season_choices import for_division
    from .season_choice_preview import base_identities
    competition=next(c for c in for_division(row['division_after']) if c.key.endswith('_ultimate_league'))
    identities=base_identities();identifier=row['cycle_before']['season_id']
    if type(identifier) is not int or not 1<=identifier<=1024:
        raise ValueError('Invalid original legacy season identity')
    if any(v[0]==identifier and k!=competition.key for k,v in identities.items()):
        raise ValueError('Legacy season ID conflicts with another admitted competition')
    if version not in ('native_forfeit_catalog_alias_v1','native_forfeit_catalog_alias_v2'):
        raise ValueError('Unknown forfeiture catalog binding')
    # The legacy slot already owns metadata resource0. Keep both cache keys
    # stable; swapping only the service ID leaves its old caption/art cached.
    metadata=0 if version.endswith('_v2') else identities[competition.key][1]
    return dict(version=version,competition_key=competition.key,
                season_id=identifier,metadata_resource_id=metadata)


def validate_record(state, row):
    from .local_seasons import CurrentSeason
    from .season_revival_policy import load_policy
    fields = {'version','policy_sha256','id','cycle_id','next_cycle_id','cycle_before',
              'target','body_hex','season_before_hex','definition_reference',
              'maintenance_threshold','division_before','division_after','points','response'}
    if isinstance(row,dict):fields|=set(row)&{'catalog_alias','same_body_predecessor'}
    if type(row) is not dict or set(row) != fields or row['version'] != VERSION:
        raise ValueError('Invalid season forfeiture receipt')
    policy()
    if row['policy_sha256'] != digest(POLICY.read_bytes()):
        raise ValueError('Forfeiture policy changed')
    uuid.UUID(row['cycle_id']); uuid.UUID(row['next_cycle_id'])
    if (row['id'] != record_id(state['account_id'],row['cycle_id'])
            or row['next_cycle_id'] != str(uuid.uuid5(uuid.UUID(row['id']),'next-cycle'))
            or row['cycle_before']['id'] != row['cycle_id']
            or row['cycle_before']['status'] != 'active'):
        raise ValueError('Forfeiture lost its original cycle identity')
    before=json.loads(bytes.fromhex(row['season_before_hex']))
    if set(before) != {'persona_id','current'} or before['persona_id'] != state['account_identity']['persona_id']:
        raise ValueError('Forfeiture season owner differs')
    current=CurrentSeason(**before['current'])
    body=json.loads(bytes.fromhex(row['body_hex']))
    from .offline_seasons_protocol import current_response
    class Recorded:
        def load(self): return current
    wire=dict(current_response(Recorded()),dataVersion=1,round=current.round_number-1)
    if (set(body) != {'round','dataVersion','data'} or type(body['round']) is not int
            or type(body['dataVersion']) is not int or body != {k:wire[k] for k in body}
            or row['target'] != f'/ut/game/fifaworldmobile/season/{current.season_id}/division/{11-current.division_index}/reset'
            or row['division_before'] != current.division_index or row['points'] != current.user_points
            or row['cycle_before']['division'] != current.division_index
            or row['cycle_before']['season_id'] != current.season_id):
        raise ValueError('Forfeiture lost its genuine original season bytes')
    threshold=load_policy().for_division(current.division_index).maintenance
    if (row['maintenance_threshold'] != threshold
            or row['division_after'] != outcome(current.division_index,current.user_points,threshold)
            or row['response'] != {'offlineDivision':11-row['division_after']}):
        raise ValueError('Forfeiture outcome/response differs from approved policy')
    ref=row['definition_reference']
    if type(ref) is not dict or not isinstance(ref.get('definition_sha256'),str) or len(ref['definition_sha256']) != 64:
        raise ValueError('Forfeiture definition reference missing')
    if 'catalog_alias' in row:
        alias=row['catalog_alias']
        if type(alias) is not dict or alias!=legacy_catalog_alias(row,alias.get('version')):
            raise ValueError('Forfeiture catalog binding differs from original legacy identity')
    if 'same_body_predecessor' in row:
        previous=next((r for r in state.get('season_forfeitures',[]) if r['id']==row['same_body_predecessor']),None)
        cycle=row['cycle_before']
        advanced=any(r['next_cycle_id']==row['cycle_id'] and r['cycle_id']==cycle.get('previous_cycle_id')
                     for r in state.get('season_forfeitures',[])+state['completions'])
        if (previous is None or previous['cycle_id']==row['cycle_id']
                or not advanced
                or (row['target'],row['body_hex'])!=(previous['target'],previous['body_hex'])
                or current.round_number!=1 or current.user_points!=0
                or not (cycle.get('season_choice_selection') or cycle.get(LEGACY_SELECTION))
                or cycle['initial_native_anchor']!=asdict(current)):
            raise ValueError('Identical empty reset lost its intervening original selection')
    return row


def validate(state):
    rows=state.get('season_forfeitures',[])
    if type(rows) is not list or len({r['cycle_id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate season forfeiture')
    for row in rows:
        validate_record(state,row)
        if any(c['cycle_id']==row['cycle_id'] for c in state['completions']):
            raise ValueError('Abandoned season cannot also complete normally')


def pending(row):
    return dict(version=PENDING,forfeit_id=row['id'],definition_reference=copy.deepcopy(row['definition_reference']))


def validate_pending(state):
    from .season_choice_pending import KEY
    marker=state['cycle'].get(KEY)
    if not isinstance(marker,dict) or marker.get('version') != PENDING:
        return False
    row=next((r for r in state.get('season_forfeitures',[]) if r['id']==marker.get('forfeit_id')),None)
    if (row is None or marker != pending(validate_record(state,row))
            or state['active_match'] is not None or state['cycle']['status'] != 'awaiting_native_initialization'
            or state['cycle']['initial_native_anchor'] is not None
            or state['cycle'].get('season_choice_selection') is not None
            or state['cycle'].get('previous_cycle_id') != row['cycle_id']
            or state['cycle']['id'] != row['next_cycle_id']
            or state['cycle']['division'] != row['division_after']):
        raise ValueError('Abandoned season lost its next original selection')
    return True


def transition(before,row):
    from .season_choice_pending import KEY
    after=copy.deepcopy(before)
    after['prepared']=None
    after.setdefault('season_forfeitures',[]).append(row)
    after['cycle']=dict(id=row['next_cycle_id'],division=row['division_after'],
        season_id=row['cycle_before']['season_id'],status='awaiting_native_initialization',
        initial_native_anchor=None,previous_cycle_id=row['cycle_id'],**{KEY:pending(row)})
    return after


def validate_intent(before,after,images):
    old=before.get('season_forfeitures',[]);new=after.get('season_forfeitures',[])
    if new == old:
        return False
    if (before['prepared'] is not None and before['prepared'].get('state_after') != after
            or type(new) is not list or new[:-1] != old or len(new) != len(old)+1
            or before['active_match'] is not None or before['cycle']['status'] != 'active'):
        raise ValueError('Forfeiture cannot rewrite history or interrupt a match')
    row=validate_record(before,new[-1])
    if row['cycle_before'] != before['cycle'] or after != transition(before,row):
        raise ValueError('Forfeiture changes unrelated journal state')
    if len(images) != 2 or {i['name'] for i in images} != {'profile.json','seasons.json'}:
        raise ValueError('Forfeiture may only change division and clear current season')
    season=next(i for i in images if i['name']=='seasons.json')
    if (season['before'] != row['season_before_hex']
            or json.loads(bytes.fromhex(season['after'])) != {'persona_id':before['account_identity']['persona_id'],'current':None}):
        raise ValueError('Forfeiture current-season image differs')
    profile=next(i for i in images if i['name']=='profile.json')
    original=json.loads(bytes.fromhex(profile['before']));expected=copy.deepcopy(original)
    expected['division_offline']=row['division_after']
    if (original['division_offline'] != row['division_before']
            or original['persona_id'] != before['account_identity']['persona_id']
            or json.loads(bytes.fromhex(profile['after'])) != expected):
        raise ValueError('Forfeiture may not change rewards or profile identity')
    validate(after);validate_pending(after)
    return True


def proposal(c,state,method,target,headers,body):
    if not selected(c.account) or method != 'PUT' or reset_path(target) is None:
        return None
    if (headers.get(b'host') != b'10.0.2.2:18081' or headers.get(b'x-ut-sid') != SID.encode()
            or headers.get(b'content-length') != str(len(body)).encode()
            or headers.get(b'content-type') != b'application/json'):
        return None
    validate(state)
    previous=next((r for r in reversed(state.get('season_forfeitures',[]))
                   if (r['target'],r['body_hex']) == (target,body.hex())),None)
    if (previous is not None and state['cycle']['id']==previous['next_cycle_id']
            and state['cycle']['status']=='awaiting_native_initialization'):
        return dict(operation='season_forfeit_retry',response=previous['response'])
    if state['active_match'] is not None or state['prepared'] is not None:
        raise ValueError('Settle the active match before forfeiting its season')
    season,_=c.stores();current=season.load()
    if current is None or state['cycle']['status'] != 'active':
        return None
    from .offline_seasons_protocol import current_response
    # Reset serializes completed matches, not the next-round save ordinal.
    # Native1233: reset round3, ordinary current round4, identical855-byte blob.
    expected=dict(current_response(season),dataVersion=1,round=current.round_number-1)
    value=json.loads(body)
    if (set(value) != {'round','dataVersion','data'} or type(value['round']) is not int
            or type(value['dataVersion']) is not int or value != {k:expected[k] for k in value}
            or target != f'/ut/game/fifaworldmobile/season/{current.season_id}/division/{11-current.division_index}/reset'):
        raise ValueError('Stale forfeiture targets a later active season' if previous else 'Forfeit request differs from current native progress')
    if (current.season_id,current.division_index) != (state['cycle']['season_id'],state['cycle']['division']):
        raise ValueError('Forfeit current season differs from accepted cycle')
    threshold=c.policy.for_division(current.division_index).maintenance
    identifier=record_id(state['account_id'],state['cycle']['id'])
    division=outcome(current.division_index,current.user_points,threshold)
    row=dict(version=VERSION,policy_sha256=digest(POLICY.read_bytes()),id=identifier,
        cycle_id=state['cycle']['id'],next_cycle_id=str(uuid.uuid5(uuid.UUID(identifier),'next-cycle')),
        cycle_before=copy.deepcopy(state['cycle']),target=target,body_hex=body.hex(),
        season_before_hex=(c.account/'seasons.json').read_bytes().hex(),
        definition_reference=definition_reference(season.definition),maintenance_threshold=threshold,
        division_before=current.division_index,division_after=division,points=current.user_points,
        response={'offlineDivision':11-division})
    if previous is not None:
        # The stock UI disables actions until QuitSeason succeeds. A genuine
        # later selection establishes a new cycle even if two empty reset
        # bodies are identical. Pending transport retries never create it.
        row['same_body_predecessor']=previous['id']
    after=transition(state,row)
    profile=json.loads((c.account/'profile.json').read_bytes());profile['division_offline']=division
    images=[c._image('profile.json',encode(profile)),c._image('seasons.json',encode(dict(persona_id=state['account_identity']['persona_id'],current=None)))]
    validate_intent(state,after,images)
    return dict(operation='season_forfeit',response=row['response'],after=after,images=images)


def validate_legacy_selection(state,definition=None):
    """A cached legacy D10 row keeps its original rules during live migration.

    Its Beginner rewards equal the approved D10 legacy policy. Other historical
    legacy divisions are not admitted; new selected competitions remain the
    normal difficulty-based path in all ten divisions.
    """
    import base64
    from .season_blob import decode_envelope
    source=state['cycle'].get(LEGACY_SELECTION)
    if source is None:return False
    cycle=state['cycle']
    fields={'version','forfeit_id','target','body_hex','definition_sha256'}
    if type(source) is not dict or set(source)!=fields or source['version']!='native_legacy_forfeit_selection_v1':
        raise ValueError('Unknown legacy forfeiture selection')
    row=next((r for r in state.get('season_forfeitures',[]) if r['id']==source['forfeit_id']),None)
    if (row is None or row['definition_reference'].get('version')!='native_forfeit_definition_v1'
            or row['division_before']!=10 or row['division_after']!=10
            or cycle['division']!=10 or cycle['status']!='active'
            or cycle['id']!=row['next_cycle_id'] or cycle.get('previous_cycle_id')!=row['cycle_id']
            or cycle.get('season_choice_selection') is not None
            or cycle['season_id']!=row['cycle_before']['season_id']
            or source['definition_sha256']!=row['definition_reference']['definition_sha256']
            or source['target']!=f"/ut/game/fifaworldmobile/season/{cycle['season_id']}/division/1/user"):
        raise ValueError('Legacy selection lost its retired season owner')
    body=json.loads(bytes.fromhex(source['body_hex']))
    if set(body)!={'round','data'} or type(body['round']) is not int or body['round']!=1:
        raise ValueError('Legacy selection needs a genuine fresh original anchor')
    wire=base64.b64decode(body['data'],validate=True);raw=decode_envelope(wire)
    expected=dict(season_id=cycle['season_id'],division_index=10,round_number=1,user_points=0,
        client_state_hex=raw.hex(),client_state_envelope_hex=wire.hex() if wire[4:]!=raw else None)
    if raw!=bytes(15) or cycle['initial_native_anchor']!=expected:
        raise ValueError('Legacy selection lost its original zero anchor')
    if definition is not None:
        from .season_choices import ChoiceDefinition
        if (isinstance(definition,ChoiceDefinition) or definition.division_index!=10
                or any(f.difficulty!=0 for f in definition.fixtures)
                or digest(encode(asdict(definition)))!=source['definition_sha256']):
            raise ValueError('Cached legacy season rules were rebound')
    return True


def validate_legacy_intent(before,after,images):
    source=after['cycle'].get(LEGACY_SELECTION)
    if source is None or source==before['cycle'].get(LEGACY_SELECTION):return False
    from .season_choice_pending import KEY
    if not validate_pending(before) or before['active_match'] is not None:
        raise ValueError('Legacy initialization needs an abandoned pending cycle')
    validate_legacy_selection(after)
    expected=copy.deepcopy(before);expected['prepared']=None
    expected['cycle'].update(status='active',initial_native_anchor=after['cycle']['initial_native_anchor'],**{LEGACY_SELECTION:source})
    expected['cycle'].pop(KEY,None)
    if after!=expected or len(images)!=1 or images[0]['name']!='seasons.json':
        raise ValueError('Legacy initialization may not change rules, rewards or history')
    old=json.loads(bytes.fromhex(images[0]['before']));new=json.loads(bytes.fromhex(images[0]['after']))
    if (old!={'persona_id':before['account_identity']['persona_id'],'current':None}
            or new!={'persona_id':before['account_identity']['persona_id'],'current':after['cycle']['initial_native_anchor']}):
        raise ValueError('Legacy initialization changes unrelated season state')
    return True


def legacy_selection_proposal(c,state,method,target,headers,body):
    from .season_choice_pending import KEY
    from .offline_seasons_protocol import parse_season_save
    from .season_choices import ChoiceDefinition
    if method!='PUT' or not validate_pending(state):return None
    marker=state['cycle'][KEY]
    row=next(r for r in state['season_forfeitures'] if r['id']==marker['forfeit_id'])
    season,_=c.stores();rules=season.definition
    if (row['division_before']!=10 or row['division_after']!=10 or isinstance(rules,ChoiceDefinition)
            or any(f.difficulty!=0 for f in rules.fixtures)
            or target!=f'/ut/game/fifaworldmobile/season/{rules.season_id}/division/1/user'):
        return None
    if season.load() is not None:raise ValueError('Legacy selection cannot replace live progress')
    current=parse_season_save(body,season)
    if (current.round_number,current.user_points)!=(1,0):raise ValueError('Fresh legacy anchor required')
    source=dict(version='native_legacy_forfeit_selection_v1',forfeit_id=row['id'],target=target,
                body_hex=body.hex(),definition_sha256=digest(encode(asdict(rules))))
    after=copy.deepcopy(state);after['prepared']=None
    after['cycle'].update(status='active',initial_native_anchor=asdict(current),**{LEGACY_SELECTION:source})
    after['cycle'].pop(KEY,None)
    images=[c._image('seasons.json',encode(dict(persona_id=state['account_identity']['persona_id'],current=asdict(current))))]
    validate_legacy_selection(after,rules);validate_legacy_intent(state,after,images)
    return dict(retry=False,legacy=True,after=after,images=images)
