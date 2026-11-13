"""Read-only stock/simulation boundary; never construct or alter native records.

An equal aggregate is not proof of a common season instance. Unchanged passthrough is
allowed only for the first simulator cycle anchored to the exact stock payload.
Genuine result inference concerns one accepted native save, not DestroyMatch ID.
"""
import hashlib
from .season_progression import reconcile, validate_progress

def payload_hash(current):
    return hashlib.sha256(bytes.fromhex(current.client_state_hex)).hexdigest()

def genuine_progression(before, after, definition):
    before.validate(definition);after.validate(definition)
    validate_progress(before.round_number-1,before.user_points)
    validate_progress(after.round_number-1,after.user_points)
    if before==after:
        return {'classification':'genuine_native_save_retry','advanced':False,'result':None}
    if after.round_number!=before.round_number+1:
        raise ValueError('Only one genuine native fixture may advance')
    delta=after.user_points-before.user_points
    result=reconcile(before.round_number-1,before.user_points,after.round_number-1,after.user_points)
    return {'classification':'genuine_native_save_progression','advanced':True,
            'result':result,'fixture_index':before.round_number,'points_delta':delta,
            'before_payload_sha256':payload_hash(before),'after_payload_sha256':payload_hash(after),
            'durable_match_identity_proven':False,'reward_eligible':False}

def synchronization_status(current, definition, view, policy):
    """Accept only an inspect() view from the guarded existing SimulationStore."""
    current.validate(definition)
    validate_progress(current.round_number-1,current.user_points)
    if view.get('classification')!='backend_simulation_only' or view.get('persona_id')!=1 or type(view.get('persona_id')) is not int:
        raise ValueError('Unsupported simulation owner or classification')
    if view.get('policy_version')!=policy.version:raise ValueError('Policy mismatch')
    target=view['current'];seed=view['initial_origin']
    validate_progress(target['played'],target['points'])
    policy.for_division(target['division']).evaluate(target['played'],target['points'])
    blockers=[]
    if view.get('pending') is not None:blockers.append('pending_simulation_transaction')
    if seed.get('origin')!='captured_stock_aggregate_reference':blockers.append('unanchored_simulation_season')
    elif (seed.get('stock_season_id')!=current.season_id or seed.get('stock_blob_sha256')!=payload_hash(current)
          or seed.get('division')!=current.division_index or seed.get('played')!=current.round_number-1
          or seed.get('points')!=current.user_points):blockers.append('stock_anchor_changed')
    # Same division/points after another completed cycle is not the same season.
    if target['sequence']!=1 or target['fixtures'] or target['completion'] is not None:
        blockers.append('native_records_for_backend_results_unavailable')
    if target['division']!=current.division_index:blockers.append('native_division_transition_uncertified')
    if (target['played'],target['points'])!=(current.round_number-1,current.user_points):
        blockers.append('native_progress_payload_unavailable')
    return {'classification':'read_only_compatibility_assessment','policy_version':policy.version,
            'stock':{'season_id':current.season_id,'division':current.division_index,
                     'played':current.round_number-1,'points':current.user_points,'payload_sha256':payload_hash(current)},
            'backend':{k:target[k] for k in ('season_instance_id','sequence','division','played','points')},
            'exact_stock_passthrough_allowed':not blockers,'blockers':blockers,
            'simulation_projection_certified':False,'genuine_match_rewards_enabled':False,
            'stock_completion_certified':False}

def require_stock_passthrough(current, definition, view, policy):
    status=synchronization_status(current,definition,view,policy)
    if not status['exact_stock_passthrough_allowed']:
        raise ValueError('Unsupported stock projection: '+', '.join(status['blockers']))
    # Return the existing object, including the untouched original envelope.
    return current


def genuine_completion_proposal(before, definition, football_store, raw_request):
    """Read a validated genuine result; propose aggregates, never native records.

    This is an explicit evidence input, not a mobile route or server receipt.
    Matching a body to a current roster does not establish lifecycle identity.
    Only normal WIN/DRAW spellings actually captured are interpreted so far.
    """
    import json
    from .destroy_match import response_for
    from .match_roster import roster_roles
    from .season_progression import advance
    before.validate(definition)
    if not isinstance(raw_request,bytes):raise ValueError('Original request bytes required')
    try:
        head,body=raw_request.split(b'\r\n\r\n',1)
        if head.splitlines()[0]!=b'PUT /ut/game/fifaworldmobile/match/end HTTP/1.1':
            raise ValueError('Not an original DestroyMatch request')
        header_lines=head.splitlines()[1:]
        if any(b':' not in line for line in header_lines):raise ValueError('Malformed header')
        headers={line.split(b':',1)[0].lower():line.split(b':',1)[1].strip() for line in header_lines}
        if len(headers)!=len(header_lines):raise ValueError('Duplicate headers')
        if response_for('PUT','/ut/game/fifaworldmobile/match/end',headers,body,football_store) is None:
            raise ValueError('Unsupported completion/ownership contract')
        value=json.loads(body)
        ours=value['myMatchStats']['goals'];theirs=value['opponentMatchStats']['goals']
    except (KeyError,IndexError,UnicodeError) as error:raise ValueError('Incomplete genuine completion evidence') from error
    if type(ours) is not int or type(theirs) is not int or not 0<=ours<=99 or not 0<=theirs<=99:
        raise ValueError('Invalid genuine score')
    expected={'WIN':'W','DRAW':'D'}
    if value['endReason'] not in expected:raise ValueError('Uncertified normal wire result spelling')
    result=expected[value['endReason']]
    if (result=='W' and ours<=theirs) or (result=='D' and ours!=theirs):
        raise ValueError('Result and genuine score disagree')
    played,points=advance(before.round_number-1,before.user_points,result)
    roles=roster_roles(football_store.load(1))
    return {'classification':'genuine_completion_aggregate_proposal_only','result':result,
            'score':[ours,theirs],'expected_round':played+1,'expected_points':points,
            'roster':roles,'native_state_available':False,'stock_commit_performed':False,
            'durable_match_identity_proven':False,'reward_eligible':False,
            'required_evidence':'matching original native SeasonUpdate and accepted/reloaded exact envelope; lifecycle binding still separate'}


def corroborate_genuine_save(before,after,definition,football_store,raw_request):
    proposal=genuine_completion_proposal(before,definition,football_store,raw_request)
    progress=genuine_progression(before,after,definition)
    if (not progress['advanced'] or progress['result']!=proposal['result'] or
        (after.round_number,after.user_points)!=(proposal['expected_round'],proposal['expected_points'])):
        raise ValueError('Native save does not corroborate the genuine result proposal')
    return {'classification':'genuine_result_and_native_save_corroboration','proposal':proposal,
            'native_progression':progress,'durable_match_identity_proven':False,'reward_eligible':False}
