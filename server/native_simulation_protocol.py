"""Captured366 CreateSim boundary; no result/opaque-state/credit authority.

Response parser022f7288 recognizes optional squad only; callback0219db80 reads
the common result. An empty ACK is a static-supported isolated candidate until
physical certification. PlaySim, end/update and durable lifecycle are separate.
"""
import hashlib,json
from .game_auth import SID
from .identity import json_response

CREATE_PATH='/ut/game/fifaworldmobile/match/sim'
END_PATH=CREATE_PATH+'/end'

def _unique(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError('Duplicate simulation key')
        value[key]=item
    return value

def inspect_create(method,target,headers,body,season_store,football_store):
    if method!='POST' or target!=CREATE_PATH:raise ValueError('Not captured CreateSim route')
    if (headers.get(b'host')!=b'10.0.2.2:18081' or headers.get(b'x-ut-sid')!=SID.encode()
        or headers.get(b'content-type')!=b'application/json' or headers.get(b'content-length')!=str(len(body)).encode()):
        raise ValueError('Wrong simulation ownership/framing')
    value=json.loads(body,object_pairs_hook=_unique)
    if type(value) is not dict or set(value)!={'squadId','type','seasonId','divisionId','customData1'}:
        raise ValueError('Unobserved simulation request fields')
    if any(type(value[k]) is not int for k in ['squadId','seasonId','divisionId','customData1']):
        raise ValueError('Invalid simulation identities')
    state=football_store.load(season_store.persona_id)
    from .squad_management import selected as management_selected
    from .local_squads import active_record,wire_id
    selected_squad=wire_id(active_record(state)) if management_selected(football_store) else 0
    if value['squadId']!=selected_squad or value['type']!='OFFLINE' or value['customData1']!=0:
        raise ValueError('Unobserved simulation mode/squad')
    current=season_store.load()
    if current is None or value['seasonId']!=current.season_id or value['divisionId']!=11-current.division_index:
        raise ValueError('Simulation season mismatch')
    if current.round_number>len(season_store.definition.fixtures):raise ValueError('Season already complete')
    owned={item.instance_id for item in state.owned_items}
    starters=[slot.instance_id for slot in state.active_lineup if slot.index<11]
    if len(starters)!=11 or len(set(starters))!=11 or not set(starters)<=owned:
        raise ValueError('Simulation needs owned current starters')
    return {'classification':'captured_native_create_sim_only','persona_id':season_store.persona_id,
        'season_id':current.season_id,'division':current.division_index,'fixture_index':current.round_number,
        'played':current.round_number-1,'points':current.user_points,'request':value,
        'body_sha256':hashlib.sha256(body).hexdigest(),'durable_match_identity_proven':False,
        'stock_progression_commit_enabled':False,'rewards_enabled':False}

def create_ack(method,target,headers,body,season_store,football_store,*,enabled=False):
    if enabled is not True:return None
    try:inspect_create(method,target,headers,body,season_store,football_store)
    except (ValueError,TypeError,KeyError,UnicodeError):return None
    return json_response({})

def play_ack(method,target,headers,body,football_store,*,enabled=False):
    """Captured367 twelve-item and429 managerless eleven-item PlaySim.

    Both use the fieldless parser0230a7bc.

    Original callback0219de34 starts the client's own simulation engine. This
    does not choose a server result or commit/reward a backend fixture.
    """
    if enabled is not True or method!='PUT' or target!=CREATE_PATH:return None
    try:
        value=json.loads(body,object_pairs_hook=_unique)
        if type(value) is not dict or set(value)!={'items'} or type(value['items']) is not list or len(value['items']) not in (11,12):return None
        if any(type(item) is not dict or set(item)!={'id'} for item in value['items']):return None
        from .local_squads import active_record
        if len(value['items'])==11 and active_record(football_store.load(1)).manager_id:return None
        from .play_game import response_for,PATH
        return response_for(method,PATH,headers,body,football_store)
    except (ValueError,TypeError,KeyError,UnicodeError):return None

def inspect_end(method,target,headers,body,season_store,football_store):
    """Read genuine369 native WIN and shared aggregate rules, without an ACK.

    The captured simulation body shares the eighteen-player completion DTO.
    Reuse its existing ownership validator; never relabel it as played gameplay.
    There is no exposed lifecycle/fixture ID and no transaction is committed.
    """
    if method!='PUT' or target!=END_PATH:raise ValueError('Not captured DestroySim route')
    from .destroy_match import response_for,PATH
    from .season_progression import advance
    if response_for(method,PATH,headers,body,football_store) is None:
        raise ValueError('Unsupported native simulation result/ownership')
    value=json.loads(body,object_pairs_hook=_unique)
    ours=value['myMatchStats'].get('goals');theirs=value['opponentMatchStats'].get('goals')
    # WIN369/370, DRAW377 and LOSS384 are genuine native observations.
    # Other result spellings remain closed until their producer is captured.
    results={'WIN':'W','DRAW':'D','LOSS':'L'}
    result=results.get(value['endReason'])
    if (result is None or type(ours) is not int or type(theirs) is not int
        or not 0<=ours<=99 or not 0<=theirs<=99
        or (result=='W' and ours<=theirs) or (result=='D' and ours!=theirs)
        or (result=='L' and ours>=theirs)):
        raise ValueError('Unobserved or inconsistent native simulation result')
    current=season_store.load()
    if current is None:raise ValueError('No native simulation season anchor')
    played,points=advance(current.round_number-1,current.user_points,result)
    return {'classification':'native_simulation_result_aggregate_proposal_only','result':result,'score':[ours,theirs],
        'expected_round':played+1,'expected_points':points,'persona_id':season_store.persona_id,
        'native_end_body_sha256':hashlib.sha256(body).hexdigest(),'durable_match_identity_proven':False,
        'native_save_observed':False,'stock_commit_performed':False,'reward_eligible':False}

def end_ack(method,target,headers,body,season_store,football_store,*,enabled=False):
    """Isolated neutral DestroySim candidate; no fixture, condition or coins write.

    Factory022f7d90 initializes reward/season-result fields to zero and installs
    VT027eedd8. Parser022f8218 accepts {} and returns1. Common callback01a5a4b4
    retires created/ID and invokes the original retained+278 delegate; only the
    original client may generate the subsequent opaque SeasonUpdate.
    """
    if enabled is not True:return None
    try:
        if headers.get(b'content-length')!=str(len(body)).encode():return None
        inspect_end(method,target,headers,body,season_store,football_store)
    except (ValueError,TypeError,KeyError,UnicodeError):return None
    return json_response({})

def corroborate_native_save(before,after,definition,football_store,raw_end):
    """Check a captured native result against its original save; no commit.

    Reuse the simulator's points rules and stock progression validator. The
    two original payloads are audit anchors, not a durable match identifier.
    Backend-generated result projection and positive rewards remain disabled.
    """
    from types import SimpleNamespace
    from .season_compatibility import genuine_progression
    if not isinstance(raw_end,bytes):raise ValueError('Original captured end bytes required')
    head,body=raw_end.split(b'\r\n\r\n',1)
    method,target,version=head.splitlines()[0].decode('ascii').split()
    lines=head.splitlines()[1:]
    if version!='HTTP/1.1' or any(b':' not in line for line in lines):raise ValueError('Invalid captured end framing')
    headers={line.split(b':',1)[0].lower():line.split(b':',1)[1].strip() for line in lines}
    if len(headers)!=len(lines) or headers.get(b'content-length')!=str(len(body)).encode():raise ValueError('Invalid captured end headers')
    before.validate(definition);after.validate(definition)
    anchor=SimpleNamespace(load=lambda:before,persona_id=football_store.load(1).persona_id)
    proposal=inspect_end(method,target,headers,body,anchor,football_store)
    progress=genuine_progression(before,after,definition)
    if (not progress['advanced'] or progress['result']!=proposal['result'] or
        (after.round_number,after.user_points)!=(proposal['expected_round'],proposal['expected_points'])):
        raise ValueError('Original native save contradicts simulation result')
    return {'classification':'native_simulation_and_original_save_corroboration',
        'native_result':proposal,'native_progression':progress,
        'opaque_state_generated':False,'stock_commit_performed':False,
        'backend_generated_result_projection_certified':False,
        'durable_match_identity_proven':False,'reward_eligible':False}

def preview_season_outcome(method,target,headers,body,season_store,football_store,policy):
    """Disabled thin v2-policy projection for the mapped original end enum.

    Parser022f8218 key1B0 reads a STRING (not a numeric wire enum):
    CHAMPIONSHIP52→4, MAINTENANCE10F→2, PROMOTION181→3, RELEGATION197→1.
    Nonzero changes the native save path; do not expose it without a durable
    completion/next-cycle coordinator and isolated client certification.
    """
    current=season_store.load()
    if current is None or current.division_index!=10:raise ValueError('Only captured native Division10 supported')
    if policy.version!='offline_seasons_console_fifa16_v2':raise ValueError('Wrong authorized policy')
    native=inspect_end(method,target,headers,body,season_store,football_store)
    outcome=policy.for_division(current.division_index).evaluate(native['expected_round']-1,native['expected_points'])
    candidate={}
    enum=0
    if outcome['complete']:
        candidate={'seasonEndResult':outcome['preview_band']}
        enum={'RELEGATION':1,'MAINTENANCE':2,'PROMOTION':3,'CHAMPIONSHIP':4}[outcome['preview_band']]
    return {'classification':'disabled_native_season_outcome_candidate',
        'policy_version':policy.version,'native_result':native,'revival_outcome':outcome,
        'candidate_response_body':candidate,'native_enum_value':enum,
        'changes_native_save_branch':enum!=0,'stock_response_activation_enabled':False,
        'profile_division_commit_enabled':False,'native_rollover_certified':False,
        'rewards_enabled':False,'opaque_state_generated':False,
        'blockers':['durable_native_season_instance_and_completion_journal_missing',
                    'nonzero_end_skips_original_SeasonUpdate_needs_completion_authority',
                    'Division9_profile_definition_and_next_cycle_not_client_certified']}

def preview_bridge(simulation_store,observation,result):
    """Use the existing guarded simulator only for a read-only proposal.

    A native request hash is evidence identity, never a fixture transaction ID.
    No commit or stock response is provided by this compatibility component.
    """
    from .season_compatibility import synchronization_status
    from .local_seasons import SeasonStore,load_definition
    view=simulation_store.inspect()
    store=SeasonStore(simulation_store.account/'seasons.json',load_definition(simulation_store.account/'definition.json'))
    current=store.load()
    if observation.get('classification')!='captured_native_create_sim_only' or observation.get('persona_id')!=1:
        raise ValueError('Unverified native simulation observation')
    if (observation['season_id'],observation['division'],observation['fixture_index'],observation['played'],observation['points'])!=(current.season_id,current.division_index,current.round_number,current.round_number-1,current.user_points):
        raise ValueError('Native simulation observation differs from stock anchor')
    status=synchronization_status(current,store.definition,view,simulation_store.policy)
    if status['blockers']:raise ValueError('Backend and stock anchors differ')
    request=simulation_store.fixture_request('native-sim-read-only-preview',[result])
    return {'classification':'disabled_native_simulation_bridge_preview','observation':observation,
        'backend_preview':simulation_store.preview(request),'stock_response':None,'commit_enabled':False,
        'blockers':['backend_selected_result_installation_not_in_observed_stock_protocol','durable_offline_lifecycle_not_exposed',
                    'server_result_override_not_in_observed_responses','shared_backend_ownership_coordinator_unimplemented']}
