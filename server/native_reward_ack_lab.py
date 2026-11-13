"""One-shot transport fault for an exact captured isolated Sim End.

This writes evidence only. It does not create, modify or recover rewards. The
existing coordinator must have committed the exact source (v1), or staged an
atomic zero-grant End (v2), before an ACK can be withheld. Never enabled on the
normal account.
"""
import hashlib
import json
import os
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[1]
KEY = 'native_reward_ack_drop_plan'
END = b'PUT /ut/game/fifaworldmobile/match/sim/end HTTP/1.1\r\n'


def claim_drop(control, account, request, response, coordinator):
    if not request.startswith(END) or control is None:
        return None
    config = json.loads(Path(control).read_bytes())
    if KEY not in config:
        return None
    account = Path(account).resolve()
    if ROOT/'reports' not in account.parents or account.name != 'isolated-account':
        raise ValueError('Lost-ACK lab requires an isolated reports account')
    if Path(control).resolve() != account/'control.json':
        raise ValueError('Lost-ACK control/account mismatch')
    plan_path = Path(config[KEY])
    if plan_path.is_symlink() or plan_path.name != 'lost-ack-plan.json':
        raise ValueError('Explicit captured lost-ACK plan required')
    run = plan_path.resolve().parent
    if run.parent != ROOT/'captures' or not run.name.startswith('run-') or not run.name[4:].isdigit():
        raise ValueError('Lost-ACK plan must belong to a reserved capture')
    # A claimed fault stays inert across retries, capture finalization and
    # process restarts, including an interrupted evidence-marker write.
    if (run/'lost-ack-claimed.json').exists():
        return None
    metadata = json.loads((run/'metadata.json').read_bytes())
    if metadata.get('finished_utc') or Path(metadata['startup_control_source']).resolve() != account/'control.json':
        raise ValueError('Lost-ACK capture is inactive or selects another account')
    plan = json.loads(plan_path.read_bytes())
    if set(plan) != {'version','account','source_id','request_sha256','response_sha256','armed_state_sha256'}:
        raise ValueError('Invalid lost-ACK plan fields')
    staged = plan['version'] == 'isolated_staged_sim_end_ack_v2'
    if plan['version'] not in ('isolated_committed_sim_end_ack_v1','isolated_staged_sim_end_ack_v2') or Path(plan['account']).resolve() != account:
        raise ValueError('Lost-ACK plan/account differs')
    uuid.UUID(plan['source_id'])
    sha = lambda raw: hashlib.sha256(raw).hexdigest()
    if plan['request_sha256'] != sha(request) or plan['response_sha256'] != sha(response):
        # Another exact-source transport operation is never faulted by this plan.
        return None
    armed_bytes = (run/'lost-ack-source-before/native-seasons.json').read_bytes()
    armed = json.loads(armed_bytes)
    original = armed.get('active_match')
    if (sha(armed_bytes) != plan['armed_state_sha256'] or armed.get('prepared')
        or not original or original['id'] != plan['source_id'] or original['status'] != 'playing'
        or not original.get('native_xp_report')
        or any(m['id'] == original['id'] for m in armed['matches'])):
        raise ValueError('Archived prospective source required before withholding reply')
    state = coordinator.recover()
    source = next((m for m in state['matches'] if m['id'] == plan['source_id']), None)
    body = request.split(b'\r\n\r\n', 1)[1]
    if staged:
        source = state['active_match']
        from .native_atomic_match import require_unchanged
        if (not source or source['id'] != plan['source_id'] or not source.get('atomic_match')
            or state['prepared'] or state['matches'] != armed['matches']
            or source.get('native_xp_report') != original['native_xp_report']
            or source.get('atomic_end',{}).get('body_hex') != body.hex()):
            raise ValueError('Exact staged atomic End source required')
        require_unchanged(coordinator,source)
    elif (state['active_match'] or state['prepared'] or source is None or source != state['matches'][-1]
          or source['status'] != 'committed' or source['end_body_hex'] != body.hex()
          or source.get('native_xp_report') != original['native_xp_report']):
        raise ValueError('Exact current completed report/End source must already be committed')
    event = {'action':'native_reward_ack_dropped_once', 'source_id':source['id'],
             'request_sha256':sha(request), 'withheld_response_sha256':sha(response),
             'plan':str(plan_path), 'reward_coins':0 if staged else source['reward_coins'],
             'reward_xp':0 if staged else source['reward_xp'], 'financial_state_changed_by_fault':False}
    if staged:
        event.update(mode='staged_atomic_match_no_grant',quoted_coins=source['atomic_end']['proposal']['reward']['amount'],
                     quoted_xp=source['native_xp_report']['quote']['xp'])
    marker = run/'lost-ack-claimed.json'
    try:
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return None
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(event, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(run, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return event
