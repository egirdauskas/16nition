"""Staged match effects in NativeSeasonCoordinator's existing recovery journal.

Report/End receipts stage ordinary match quotes until the original season save.
A season-final End already closes the cycle in the recovered stock contract,
so it commits combined Profile/Season/Definition images there. No opaque
progress is generated and no historical grant is migrated or rolled back.
"""
import copy
import hashlib
import json
from dataclasses import asdict, replace

VERSION = 'native_atomic_match_v1'
DEPLOYMENT = 'atomic-match-release.json'
# Presentation is provisional only in the process/session which accepted the
# report. Backend restart or genuine authentication discards this UI cache.
PRESENTATION = {}


def validate_deployment(account):
    """Explicit archived admission of this policy; old deployments stay intact."""
    from pathlib import Path
    root=Path(__file__).resolve().parents[1];account=Path(account).resolve()
    real=root/'server/data/development/fm16in2026'
    if account!=real and (root/'reports' not in account.parents or account.name!='isolated-account'):
        raise ValueError('Atomic deployment account differs')
    marker=account/DEPLOYMENT
    if marker.is_symlink():raise ValueError('Atomic deployment alias refused')
    value=json.loads(marker.read_bytes())
    if (set(value)!={'version','account','origin_archive','origin_manifest_sha256','certificate','certificate_sha256'}
        or value['version']!=VERSION or value['account']!=str(account)):
        raise ValueError('Invalid atomic deployment marker')
    archive=Path(value['origin_archive']).resolve();certificate=Path(value['certificate']).resolve()
    if root/'reports' not in archive.parents or archive==account or account in archive.parents or root/'reports' not in certificate.parents or certificate.is_symlink():
        raise ValueError('Separate preserved atomic deployment evidence required')
    manifest=json.loads((archive/'.lab-snapshot.json').read_bytes())
    if sha((archive/'.lab-snapshot.json').read_bytes())!=value['origin_manifest_sha256']:
        raise ValueError('Atomic deployment archive changed')
    for name,digest in manifest['sha256'].items():
        path=archive/name
        if Path(name).name!=name or path.is_symlink() or sha(path.read_bytes())!=digest:
            raise ValueError('Atomic deployment archive changed')
    old=json.loads((archive/'profile.json').read_bytes());current=json.loads((account/'profile.json').read_bytes())
    if any(old[k]!=current[k] for k in ('persona_id','identity_pid','user_id')):
        raise ValueError('Atomic deployment owner changed')
    if sha(certificate.read_bytes())!=value['certificate_sha256']:
        raise ValueError('Atomic match certificate changed')
    proof=json.loads(certificate.read_bytes())
    required={'status':'STOCK_VERIFIED_ATOMIC_MATCH_SAVE','commit_point':'genuine_native_season_save',
              'restart_verified':True,'failure_zero_effects':True,'exact_retry_verified':True,'reauthentication_abort_verified':True}
    if any(type(proof.get(k)) is not type(v) or proof[k]!=v for k,v in required.items()) or not all(type(proof.get(k)) is int and proof[k]>0 for k in ('native_success_capture','native_failure_capture','native_reconnect_capture')):
        raise ValueError('Atomic match certificate incomplete')
    return value


def read_response(coordinator, state, method, target, headers, body):
    """Existing wire fields only; no durable grant from a provisional display."""
    from .victory_session import is_authentication
    if is_authentication(method, target):
        PRESENTATION.pop(str(coordinator.account), None)
    source = state['active_match']
    if not source or not source.get('atomic_match'):
        return None
    from .local_profile import load_profile
    profile = load_profile(coordinator.account/'profile.json')
    if (method == 'GET' and target == '/victory_fwm_s2/Engine.svc/User/Persona/GetExtendedUserPlate'
            and not body and headers.get(b'host') == b'10.0.2.2:18081'
            and headers.get(b'securitytoken') == profile.victory_security_token.encode()
            and headers.get(b'userid') == profile.user_id.encode()
            and PRESENTATION.get(str(coordinator.account)) == source['id']
            and source.get('native_xp_report')):
        from .victory_session import xml_response
        q = source['native_xp_report']['quote']['after']
        ns = 'http://schemas.datacontract.org/2004/07/Victory.FW.Components.AccountFeature.TransferObjects'
        from .favorites import plate_xml
        favorite = plate_xml(profile)
        return xml_response(f'<Response xmlns="{ns}"><DeltaExperience>{q["level_xp"]}</DeltaExperience><DeltaLvExp>{q["next_level_xp"]}</DeltaLvExp><Level>{q["level"]}</Level>{favorite}</Response>')
    return None


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pinned(source):
    marker = source.get('atomic_match')
    if (type(marker) is not dict or set(marker) not in ({'version', 'profile_before_hex', 'season_before_hex'},
            {'version', 'profile_before_hex', 'season_before_hex', 'competition_reference'})
            or marker['version'] != VERSION):
        raise ValueError('Invalid atomic match start')
    return bytes.fromhex(marker['profile_before_hex']), bytes.fromhex(marker['season_before_hex'])


def require_unchanged(coordinator, source):
    profile, season = pinned(source)
    if 'competition_reference' in source['atomic_match']:
        from .season_choice_reference import snapshot, resolve
        current = coordinator.stores()[0].definition
        if snapshot(current) != source['atomic_match']['competition_reference']:
            raise ValueError('Atomic competition changed before commit')
        resolve(current, source)
    if ((coordinator.account/'profile.json').read_bytes() != profile
            or (coordinator.account/'seasons.json').read_bytes() != season):
        raise ValueError('Atomic match projections changed before commit')
    pack=source.get('atomic_pack')
    if pack:
        from .atomic_pack_reference import compact,baseline
        raw=(coordinator.account/'packs.json').read_bytes()
        if compact(pack):baseline(pack,raw)
        elif raw!=bytes.fromhex(pack['packs_before_hex']):
            raise ValueError('Atomic pack projections changed before commit')


def validate_pack_start(coordinator,source):
    pack=source.get('atomic_pack')
    if not pack:return
    from .native_match_pack_policy import validate_snapshot,snapshot,PATH_V6,STORE_PARITY_PATH
    from .atomic_pack_reference import compact,validate as validate_reference
    if not source.get('atomic_match') or type(pack) is not dict:
        raise ValueError('Invalid atomic pack start')
    if compact(pack):validate_reference(pack,source['status']=='committed')
    elif set(pack)-{'grant','championship_start'}!={'policy','packs_before_hex'}:
        raise ValueError('Invalid atomic pack start')
    policy=validate_snapshot(pack['policy'])
    path=STORE_PARITY_PATH if policy['version']=='reward_store_parity_v1' else PATH_V6
    if (policy['division']!=source['native_xp_start']['division'] or
            (path==PATH_V6 and policy!=snapshot(source['native_xp_start']['division'],path))):
        raise ValueError('Atomic pack policy differs from accepted division')
    if not compact(pack):
        before=json.loads(bytes.fromhex(pack['packs_before_hex']))
        if before.get('prepared') or before['persona_id']!=1:
            raise ValueError('Quiescent owned pack start required')
    if source['status']!='committed' and 'grant' in pack:
        raise ValueError('Uncommitted source cannot grant a pack')
    title=pack.get('championship_start')
    if source.get('season_coin_start') is not None:
        from .native_match_pack_policy import championship_definition
        from .native_championship_packs import snapshot as title_snapshot
        division=source['native_xp_start']['division']
        definition=championship_definition(division,path)
        if title!=(title_snapshot(division,definition) if definition else None):
            raise ValueError('Atomic title differs from prospective pack policy')
    elif title is not None:
        raise ValueError('Atomic title requires prospective season rewards')


def pack_image(state,source,*,before_raw=None):
    """Existing PackStore entitlement image; no separate financial commit."""
    import uuid
    from .local_packs import PackStore
    from .native_season_completion import encode
    pack=source['atomic_pack']
    definition=pack['policy']['outcomes'][source['result']]['definition']
    from .atomic_pack_reference import compact,baseline as reference_baseline,grant as reference_grant
    if compact(pack) and source['status']=='committed' and before_raw is None:
        return None,reference_grant(state,source,definition)
    receipt={'reward_id':str(uuid.uuid5(uuid.UUID(source['id']),'fixture-pack')),
        'source_id':source['id'],'source_kind':'fixture','account_id':state['account_id'],
        'persona_id':state['account_identity']['persona_id'],'cycle_id':source['cycle_id'],
        'policy_version':'reward_store_parity_v1' if pack['policy']['version']=='reward_store_parity_v1' else 'backend_pack_entitlement_test_v1','certification':'backend_only'}
    baseline=(reference_baseline(pack,before_raw) if compact(pack)
              else json.loads(bytes.fromhex(pack['packs_before_hex'])))
    for prior in baseline.get('source_grants',[]):
        if (prior['account_id'] != state['account_id']
                or prior['persona_id'] != receipt['persona_id']):
            raise ValueError('Foreign or conflicting atomic pack source owner')
        # Independent sources keep their own provenance validators. They are
        # not Seasons completions; every source still shares this account owner.
        kind, policy = prior['source_kind'], prior['policy_version']
        if kind == 'setup' and policy == 'first_run_v1':
            creation = uuid.UUID(prior['cycle_id'])
            expected_sources = {
                str(uuid.uuid5(creation, 'welcome-pack:%d' % ordinal))
                for ordinal in range(5)
            }
            if (str(uuid.uuid5(creation, 'account')) != state['account_id']
                    or prior['source_id'] not in expected_sources):
                raise ValueError('Atomic pack setup source differs from account creation')
            continue
        if ((kind == 'level' and policy == 'level_rewards_v1')
                or (kind == 'accomplishment' and policy == 'accomplishments_v1')
                or (kind in ('fixture', 'season') and policy == 'tournament_rewards_v2')):
            continue
        owners=state['matches'] if prior['source_kind']=='fixture' else state['completions']
        owner=next((s for s in owners if s['id']==prior['source_id']),None)
        if (prior['account_id']!=state['account_id'] or prior['persona_id']!=receipt['persona_id']
            or owner is None or owner['status']!='committed' or owner['cycle_id']!=prior['cycle_id']):
            raise ValueError('Foreign or conflicting atomic pack source owner')
    value,grant=PackStore.source_grant_image(baseline,definition,receipt)
    if compact(pack) and grant!=reference_grant(state,source,definition):
        raise ValueError('Compact fixture grant differs from pinned allocator')
    return encode(value),grant


def validate_pack_ownership(coordinator,state):
    sources=[s for s in state['matches'] if s.get('atomic_pack') and not s.get('native_match_forfeit')]
    forfeited={s['id'] for s in state['matches'] if s.get('native_match_forfeit')}
    forfeited.update(c['id'] for c in state['completions'] if c['receipt_id'] in forfeited)
    if not sources and not forfeited:return
    from .local_packs import PackStore
    value=PackStore(coordinator.account/'packs.json').load()
    # One owned-pack read/index per recovery, never one full history read for
    # every forfeited match. A forfeiture cannot own either kind of pack grant.
    if any(g['source_id'] in forfeited for g in value.get('source_grants',[])):
        raise ValueError('A forfeited source cannot own an earned pack grant')
    for source in sources:
        if source.get('level_reward') is not None:
            if level_quote(source) != source['level_reward']['quote'] or any(
                    g not in value.get('source_grants',[]) for g in source['level_reward']['grants']):
                raise ValueError('Level reward ownership differs')
        if 'season_choice_handoff' in source:
            if (source['season_choice_handoff']!={'version':'native_legacy_choice_handoff_v1'} or
                    not source.get('atomic_match') or 'competition_reference' in source['atomic_match']):
                raise ValueError('Invalid prospective legacy-choice handoff source')
        _,grant=pack_image(state,source)
        if source['atomic_pack'].get('grant')!=grant or grant not in value.get('source_grants',[]):
            raise ValueError('Atomic committed pack ownership differs')
    for completion in state['completions']:
        pack=completion.get('atomic_season_pack')
        if pack and pack['grant'] is not None and pack['grant'] not in value.get('source_grants',[]):
            raise ValueError('Atomic championship pack ownership differs')


def season_pack_image(state,source,completion,raw):
    """Add a separate title source to the same existing PackStore image."""
    import uuid
    from .local_packs import PackStore
    from .native_season_completion import encode
    start=source.get('atomic_pack',{}).get('championship_start')
    if start is None:return raw,None
    from .native_championship_packs import validate_snapshot
    validate_snapshot(start)
    grant=None
    if completion['outcome']['preview_band']=='CHAMPIONSHIP':
        receipt={'reward_id':str(uuid.uuid5(uuid.UUID(completion['id']),'season-pack')),
            'source_id':completion['id'],'source_kind':'season','account_id':state['account_id'],
            'persona_id':state['account_identity']['persona_id'],'cycle_id':source['cycle_id'],
            'policy_version':'reward_store_parity_v1' if source['atomic_pack']['policy']['version']=='reward_store_parity_v1' else 'backend_pack_entitlement_test_v1','certification':'backend_only'}
        from .atomic_pack_reference import compact,grant as reference_grant
        if raw is None and compact(source['atomic_pack']):
            grant=reference_grant(state,source,start['definition'],completion=completion)
        else:
            value,grant=PackStore.source_grant_image(json.loads(raw),start['definition'],receipt)
            raw=encode(value)
            if compact(source['atomic_pack']) and grant!=reference_grant(state,source,start['definition'],completion=completion):
                raise ValueError('Compact title grant differs from pinned allocator')
    return raw,{'start':copy.deepcopy(start),'grant':grant}


def validate_season_completions(state):
    """Validate new combined receipts without reinterpreting historical finals."""
    import uuid
    for completion in state['completions']:
        source=next(s for s in state['matches'] if s['id']==completion['receipt_id'])
        if source.get('native_match_forfeit'):
            from .native_match_forfeit_final import validate_completion
            validate_completion(source,completion,state)
            continue
        if not source.get('atomic_match') or not source.get('season_coin_start'):
            if completion.get('atomic_season_pack') is not None:
                raise ValueError('No retroactive atomic championship pack')
            continue
        if (completion['id']!=str(uuid.uuid5(uuid.UUID(source['id']),'season-completion')) or
                completion['next_cycle_id']!=str(uuid.uuid5(uuid.UUID(source['id']),'next-season-cycle')) or
                completion.get('season_coin_start')!=source['season_coin_start']):
            raise ValueError('Atomic season completion identity/snapshot mismatch')
        raw,_=pack_image(state,source) if source.get('atomic_pack') else (None,None)
        _,expected=season_pack_image(state,source,completion,raw)
        if completion.get('atomic_season_pack')!=expected:
            raise ValueError('Atomic championship grant differs from final source')
        from .native_season_coin_rewards import validate_final_source
        validate_final_source(source,completion,source['native_xp_start']['division'])
        rewards=[r for r in state.get('season_coin_rewards',[]) if r['source_id']==completion['id']]
        if len(rewards)!=1:raise ValueError('Atomic final must commit its season coins together')
        from .native_season_completion import encode
        from .native_season_coin_rewards import quote,reward_image
        raw,season=pinned(source)
        profile=json.loads(raw)
        profile.update(credits=source['reward']['credits_after'],
            revival_total_xp=source['native_xp_report']['quote']['after']['total_xp'],
            division_offline=completion['outcome']['proposed_next_division'])
        raw=encode(profile)
        if (completion['original_pre_final_state']!=json.loads(season)['current'] or
                completion.get('season_coin_delivery')!={'quote':quote(source['season_coin_start'],completion['outcome']['preview_band']),
                    'credits_before':profile['credits'],'profile_before_sha256':sha(raw)}):
            raise ValueError('Atomic season delivery differs from pinned final wallet')
        if reward_image(state,completion,raw)[1]!=rewards[0]:
            raise ValueError('Atomic season receipt differs from combined wallet image')


def report_image(source):
    from .native_season_completion import encode
    raw, _ = pinned(source)
    profile = json.loads(raw)
    profile['revival_total_xp'] = source['native_xp_report']['quote']['after']['total_xp']
    return encode(profile)


def validate_report(source, state):
    from .native_match_xp import validate_source
    validate_source(source, state)
    report = source['native_xp_report']
    raw, _ = pinned(source)
    if (sha(raw) != report['profile_before_sha256']
            or sha(report_image(source)) != report['profile_after_sha256']):
        raise ValueError('Atomic staged report/profile mismatch')


def validate_staged_source(coordinator, state):
    validate_season_completions(state)
    aborted=state.get('aborted_matches',[])
    if type(aborted) is not list:raise ValueError('Invalid aborted source history')
    sources = ([state['active_match']] if state['active_match'] else []) + state['matches'] + aborted
    if len({s['id'] for s in sources})!=len(sources):raise ValueError('Native source identity reused')
    for source in aborted:
        if source.get('status')!='aborted' or source.get('abort_reason')!='reauthenticated_before_match_commit' or not source.get('atomic_match') or source.get('reward') or source.get('native_atomic_save') or source.get('native_atomic_final'):
            raise ValueError('Invalid zero-effect aborted source')
    for source in sources:
        from .training_expiry import validate_source as validate_training
        validate_training(source)
        from .injury_effects import validate_source as validate_injury
        validate_injury(source)
        if source.get('native_match_forfeit'):
            from .native_match_forfeit import validate_source as validate_forfeit
            validate_forfeit(source,state,coordinator)
            if source['status']=='committed':continue
        elif source.get('native_forfeit_report'):
            from .native_match_forfeit import validate_report as validate_forfeit_report
            validate_forfeit_report(source,coordinator)
        if 'division_season_identity' in source and not source.get('atomic_match'):
            raise ValueError('Pinned division season identity requires an atomic source')
        if not source.get('atomic_match'):
            continue
        from .season_completion_timing import validate_source as validate_timing
        validate_timing(source)
        raw, season_raw = pinned(source)
        from .season_choice_reference import resolve as source_definition
        source_definition(coordinator.stores()[0].definition, source, state.get('season_definition_history'))
        validate_pack_start(coordinator,source)
        profile, season = json.loads(raw), json.loads(season_raw)['current']
        if source.get('division_season_identity') is not None:
            from .native_division_season_identity import next_id
            next_id(source,{'proposed_next_division':season['division_index']})
        if (profile['persona_id'] != state['account_identity']['persona_id']
                or profile['identity_pid'] != state['account_identity']['identity_pid']
                or profile['user_id'] != state['account_identity']['user_id']
                or profile.get('revival_total_xp', 0) != source['native_xp_start']['total_xp']
                or season['round_number'] != source['fixture']
                or season['division_index'] != source['native_xp_start']['division']):
            raise ValueError('Atomic start differs from accepted identity/fixture')
        if source.get('native_xp_report'):
            validate_report(source, state)
        if source.get('atomic_end') and source['status']!='aborted':
            proposal = source['atomic_end']['proposal']
            if proposal != pure_end_proposal(coordinator, state, source, bytes.fromhex(source['atomic_end']['body_hex'])):
                raise ValueError('Staged End policy/result mismatch')
        if source.get('level_reward_start') is not None:
            from .level_rewards import validate_start
            validate_start(source['level_reward_start'])
            if not source.get('atomic_pack') or not source.get('native_xp_start'):
                raise ValueError('Level rewards require atomic packs and XP')
        if source['status'] == 'committed':
            expected_level = level_quote(source) if source.get('native_xp_report') else None
            if (source.get('level_reward') or {}).get('quote') != expected_level:
                raise ValueError('Level reward receipt differs from accepted report')
            if source.get('atomic_pack') and source['atomic_pack'].get('grant')!=pack_image(state,source)[1]:
                raise ValueError('Atomic committed pack receipt differs')
            saved = source.get('native_atomic_save')
            final_end=source.get('native_atomic_final') is True
            if (not final_end and (type(saved) is not dict or set(saved) != {'target','body_hex'})) or (final_end and saved is not None) or source.get('atomic_end'):
                raise ValueError('Atomic committed source missing original save')
            profile.update(credits=source['reward']['credits_after'],
                           revival_total_xp=source['native_xp_report']['quote']['after']['total_xp'])
            from .season_completion_timing import source_outcome
            outcome = source_outcome(source,source['native_xp_start']['division'],source['points_after'],season_policy=coordinator.policy)
            if outcome['complete']!=final_end:raise ValueError('Atomic final commit point differs from outcome')
            if outcome['complete']:profile['division_offline']=outcome['proposed_next_division']
            from .native_season_completion import encode
            if sha(encode(profile)) != source['reward']['profile_after_sha256'] or sha(raw) != source['reward']['profile_before_sha256']:
                raise ValueError('Atomic committed combined profile mismatch')
            if final_end:continue
            from .local_seasons import SeasonStore,CurrentSeason
            from .offline_seasons_protocol import parse_season_save
            store,_=coordinator.stores()
            division=outcome['proposed_next_division'] if outcome['complete'] else source['native_xp_start']['division']
            definition=source_definition(store.definition,source,state.get('season_definition_history'))
            class SavedBefore(SeasonStore):
                def load(self):
                    return None if outcome['complete'] else CurrentSeason(**json.loads(season_raw)['current'])
            current=parse_season_save(bytes.fromhex(saved['body_hex']),SavedBefore(store.path,definition)).validate(definition)
            expected=(1,0) if outcome['complete'] else (source['fixture']+1,source['points_after'])
            if ((current.round_number,current.user_points)!=expected
                or saved['target']!=f'/ut/game/fifaworldmobile/season/{definition.season_id}/division/{11-division}/user'):
                raise ValueError('Atomic committed native save mismatch')


def abort_for_authentication(coordinator,before,method,target,headers,body):
    """A new genuine login retires an uncommitted attempt, never a committed one.

    HTTP Connection:close is normal on this protocol, so socket EOF alone is not
    a session-abort signal. Retain the exact failed attempt as a tombstone.
    """
    source=before['active_match']
    if not source or not source.get('atomic_match'):return None
    from .victory_session import response_for
    if response_for(method,target,headers,body,before['account_identity']['persona_id']) is None:return None
    after=copy.deepcopy(before)
    retired=copy.deepcopy(source);retired.update(status='aborted',abort_reason='reauthenticated_before_match_commit')
    after.setdefault('aborted_matches',[]).append(retired);after['active_match']=None
    coordinator._transaction(before,after,[])
    PRESENTATION.pop(str(coordinator.account),None)
    return {'operation':'atomic_session_abort','preserve_response':True}


def pure_end_proposal(coordinator, state, source, body):
    from .local_seasons import SeasonStore, CurrentSeason
    from .native_played_protocol import protocol
    mode=protocol(source);inspect_end,END_PATH=mode.inspect_end,mode.END_PATH
    from .revival_rewards import match_coin_quote
    from .native_match_reward_policy import response_fields
    from .local_profile import validate_credits
    season, football = coordinator.stores()
    if source.get('atomic_end') is not None:
        football = recorded_end_roster(source, body)
    division = source['native_xp_start']['division']
    from .season_choice_reference import resolve as source_definition
    definition = source_definition(season.definition, source, state.get('season_definition_history'))
    class BeforeSeason(SeasonStore):
        def load(self):
            return CurrentSeason(**json.loads(pinned(source)[1])['current']).validate(definition)
    headers = {b'host':b'10.0.2.2:18081',b'x-ut-sid':b'fifa16-local-sid',
               b'content-length':str(len(body)).encode(),b'content-type':b'application/json'}
    observation = inspect_end('PUT',END_PATH,headers,body,BeforeSeason(season.path,definition),football)
    from .injury_effects import validate_end as validate_injury_end
    validate_injury_end(source,body)
    report = source.get('native_xp_report')
    if not report or (report['observation']['score'],report['observation']['result']) != (observation['score'],observation['result']):
        raise ValueError('Atomic End contradicts report')
    from .season_completion_timing import source_outcome
    outcome = source_outcome(source,division,observation['expected_points'],season_policy=coordinator.policy)
    from .difficulty_rewards import source_coin_quote
    calculation = source_coin_quote(source,observation['result'])
    raw,_ = pinned(source);profile=json.loads(raw)
    reward = {'policy_version':source['coin_reward_start']['policy_version'],'classification':'revival_policy','quote':calculation,
              'amount':calculation['amount'],'credits_before':profile['credits'],
              'credits_after':validate_credits(profile['credits']+calculation['amount']), 'profile_before_sha256':sha(raw)}
    response = response_fields(reward['amount'])
    if source.get('season_coin_start') is not None:
        from .native_season_coin_rewards import awards_response,quote
        response=awards_response(source['season_coin_start'],outcome,reward['amount'])
        if outcome['complete']:
            validate_credits(reward['credits_after']+quote(source['season_coin_start'],outcome['preview_band'])['amount'])
    if outcome['complete']:response['seasonEndResult']=outcome['preview_band']
    return {'operation':'end','observation':observation,'outcome':outcome,'response':response,'reward':reward,'progression':None}


def recorded_end_roster(source, body):
    """Read already accepted End membership without consulting today's squad.

    The first End still passes the ordinary live ownership/roster validator.
    This view is used only to validate the exact journaled End later. Save
    admission independently requires unchanged projections and a live End check.
    No second roster history, ownership or client state is created.
    """
    from types import SimpleNamespace
    staged = source['atomic_end']
    observation = staged['proposal']['observation']
    if (body.hex() != staged['body_hex']
            or sha(body) != observation['native_end_body_sha256']):
        raise ValueError('Recorded End bytes differ from accepted observation')
    rows = json.loads(body)['items']
    ids = [row['id'] for row in rows]
    if (not 11 <= len(ids) <= 18 or len(ids) != len(set(ids))
            or any(type(key) is not int or not 0 < key <= 0x7fffffffffffffff for key in ids)):
        raise ValueError('Invalid recorded End roster')
    from .training_expiry import ids as play_ids
    entered = play_ids(bytes.fromhex(source['play_body_hex']))
    if len(entered & set(ids)) < 11:
        raise ValueError('Recorded End lost the accepted initial players')
    state = SimpleNamespace(
        owned_items=tuple(SimpleNamespace(instance_id=key) for key in ids),
        active_lineup=tuple(SimpleNamespace(index=index, instance_id=key)
                            for index, key in enumerate(ids)),
    )
    return SimpleNamespace(load=lambda persona: state)


def end_proposal(coordinator, state, source):
    """Recompute from authenticated framing and stored original End bytes."""
    staged = source['atomic_end']
    if set(staged) != {'body_hex', 'proposal'}:
        raise ValueError('Invalid staged End schema')
    body = bytes.fromhex(staged['body_hex'])
    before = copy.deepcopy(state)
    before['active_match'].pop('atomic_end')
    headers = {b'host': b'10.0.2.2:18081', b'x-ut-sid': b'fifa16-local-sid',
               b'content-length': str(len(body)).encode(), b'content-type': b'application/json'}
    from .native_played_protocol import protocol
    END_PATH=protocol(source).END_PATH
    expected = coordinator._proposal(before, 'PUT', END_PATH, headers, body)
    if staged['proposal'] != expected or expected['operation'] != 'end':
        raise ValueError('Staged End differs from accepted report/result/policy')
    return expected


def save_proposal(coordinator, state, method, target, headers, body):
    source = state['active_match']
    def recorded_retry():
        for receipt in reversed(state['matches']):
            saved=receipt.get('native_atomic_save')
            if saved and target==saved['target'] and body.hex()==saved['body_hex'] and valid_save_owner(method,headers,body):
                return {'operation':'atomic_save_retry','response':{}}
        return None
    def refuse_stale_identity():
        if not valid_save_owner(method,headers,body):return
        completed=next((c for c in reversed(state['completions']) if c['next_cycle_id']==state['cycle']['id']),None)
        previous=next((s for s in state['matches'] if completed and s['id']==completed['receipt_id']),None)
        if previous and previous.get('division_season_identity'):
            expected=f"/ut/game/fifaworldmobile/season/{state['cycle']['season_id']}/division/{11-state['cycle']['division']}/user"
            if target!=expected:raise ValueError('Stale native season identity; no initialization accepted')
    if source is None and state['cycle']['status']=='awaiting_native_initialization' and valid_save_owner(method,headers,body):
        from .season_choice_pending import KEY
        if KEY in state['cycle']:
            # Only the explicit selection adapter may install a next anchor.
            return recorded_retry()
        season,_=coordinator.stores()
        expected=f'/ut/game/fifaworldmobile/season/{season.definition.season_id}/division/{11-season.definition.division_index}/user'
        if target!=expected:
            retry=recorded_retry()
            if retry:return retry
            refuse_stale_identity()
            return None
        from .offline_seasons_protocol import parse_season_save
        current=parse_season_save(body,season).validate(season.definition)
        if current.round_number!=1 or current.user_points!=0:raise ValueError('Original next-season initialization required')
        return {'operation':'atomic_initialization','response':{},'current':asdict(current)}
    if not source or not source.get('atomic_match') or not source.get('atomic_end'):
        if source is None and state['cycle']['status']=='active' and valid_save_owner(method,headers,body):
            anchor=state['cycle'].get('initial_native_anchor')
            if anchor and anchor['round_number']==1 and not any(m['cycle_id']==state['cycle']['id'] for m in state['matches']):
                season,_=coordinator.stores()
                expected=f'/ut/game/fifaworldmobile/season/{season.definition.season_id}/division/{11-season.definition.division_index}/user'
                if target==expected:
                    from .offline_seasons_protocol import parse_season_save
                    current=parse_season_save(body,season)
                    if asdict(current)==anchor and current==season.load():
                        return {'operation':'atomic_initialization_retry','response':{}}
        # Exact save retry is bound to the committed source, not any PUT.
        retry=recorded_retry()
        if retry:return retry
        if source is None:refuse_stale_identity()
        return None
    require_unchanged(coordinator, source)
    if source.get('atomic_pack'):coordinator._check_pack_capacity(1)
    if not valid_save_owner(method, headers, body):
        return None
    end = end_proposal(coordinator, state, source)
    season, _ = coordinator.stores()
    if end['outcome']['complete']:raise ValueError('Final match closes atomically at genuine End, not a future season save')
    definition = season.definition
    expected_target = f'/ut/game/fifaworldmobile/season/{definition.season_id}/division/{11-definition.division_index}/user'
    if target != expected_target:
        return None
    from .local_seasons import SeasonStore
    from .offline_seasons_protocol import parse_season_save
    current = parse_season_save(body,season).validate(definition)
    observation = end['observation']
    if (current.round_number, current.user_points) != (observation['expected_round'], observation['expected_points']):
        raise ValueError('Atomic native save contradicts completed result')
    return {'operation': 'atomic_save', 'response': {}, 'current': asdict(current),
            'save': {'target': target, 'body_hex': body.hex()}}


def valid_save_owner(method, headers, body):
    return (method == 'PUT' and headers.get(b'host') == b'10.0.2.2:18081'
            and headers.get(b'x-ut-sid') == b'fifa16-local-sid'
            and headers.get(b'content-length') == str(len(body)).encode()
            and headers.get(b'content-type') == b'application/json')


def final_state(coordinator, before, proposal, *, pack_before=None,football_before=None):
    """Build all images once; the existing journal owns commit and recovery."""
    from .native_season_completion import encode, digest
    import uuid
    after = copy.deepcopy(before)
    after['prepared'] = None
    source = after['active_match']
    end = source.pop('atomic_end')['proposal']
    observation, outcome = end['observation'], end['outcome']
    raw, _ = pinned(source)
    profile = json.loads(raw)
    profile.update(credits=end['reward']['credits_after'],
                   revival_total_xp=source['native_xp_report']['quote']['after']['total_xp'])
    if outcome['complete']:
        profile['division_offline'] = outcome['proposed_next_division']
    data = encode(profile)
    reward = copy.deepcopy(end['reward'])
    reward.update(id=str(uuid.uuid5(uuid.UUID(source['id']), 'native-match-coins')),
                  source_receipt_id=source['id'], account_id=before['account_id'],
                  persona_id=before['account_identity']['persona_id'], cycle_id=source['cycle_id'],
                  fixture_index=source['fixture'], status='committed', profile_after_sha256=digest(data))
    source.update(status='committed', end_body_hex=before['active_match']['atomic_end']['body_hex'],
                  result=observation['result'], score=observation['score'], points_after=observation['expected_points'],
                  response=end['response'], provenance='original_native_played' if source.get('played_match') else 'original_native_simulation',
                  reward_coins=reward['amount'], reward_xp=source['native_xp_report']['quote']['xp'],
                  reward=reward)
    if outcome['complete']:source['native_atomic_final']=True
    else:source['native_atomic_save']=proposal['save']
    after['matches'].append(source)
    after['active_match'] = None
    images = [coordinator._image('profile.json', data),
              coordinator._image('seasons.json', encode({'persona_id':before['account_identity']['persona_id'], 'current':proposal['current']}))]
    from .injury_effects import match_image as training_image
    expired=training_image(coordinator,source,before_raw=football_before)
    if expired is not None:images.append(expired)
    if source.get('atomic_pack'):
        from .atomic_pack_reference import compact
        if compact(source['atomic_pack']):
            pack_before=(coordinator.account/'packs.json').read_bytes() if pack_before is None else pack_before
        pack_data,grant=pack_image(before,source,before_raw=pack_before)
        source['atomic_pack']['grant']=grant
        images.append({'name':'packs.json','before':pack_before.hex() if compact(source['atomic_pack']) else source['atomic_pack']['packs_before_hex'],'after':pack_data.hex()})
        if compact(source['atomic_pack']):source['atomic_pack'].pop('packs_before_sha256')
    if outcome['complete']:
        combined=source.get('season_coin_start') is not None
        next_id = str(uuid.uuid5(uuid.UUID(source['id']),'next-season-cycle')) if combined else str(uuid.uuid4())
        from .native_division_season_identity import next_id as next_season_id
        wire_season_id=next_season_id(source,outcome)
        # Keep the recovered legacy flag unchanged. Authorized revival effects
        # have their own prospective, independently identified receipts below.
        completion={'id':str(uuid.uuid5(uuid.UUID(source['id']),'season-completion')) if combined else str(uuid.uuid4()), 'cycle_id':before['cycle']['id'],
            'receipt_id':source['id'], 'policy_version':before['policy_version'], 'outcome':outcome,
            'original_pre_final_state':json.loads(bytes.fromhex(source['atomic_match']['season_before_hex']))['current'],
            'final_native_result':observation, 'next_cycle_id':next_id, 'status':'committed', 'rewards_enabled':False}
        after['completions'].append(completion)
        if combined:
            from .native_season_coin_rewards import quote,reward_image
            completion['season_coin_start']=copy.deepcopy(source['season_coin_start'])
            completion['season_coin_delivery']={'quote':quote(source['season_coin_start'],outcome['preview_band']),
                'credits_before':profile['credits'],'profile_before_sha256':digest(data)}
            final_data,season_reward=reward_image(after,completion,data)
            after.setdefault('season_coin_rewards',[]).append(season_reward)
            images[0]['after']=final_data.hex()
            if source.get('atomic_pack'):
                pack_data,title=season_pack_image(after,source,completion,pack_data)
                if title is not None:completion['atomic_season_pack']=title
                next(i for i in images if i['name']=='packs.json')['after']=pack_data.hex()
        after['cycle'] = {'id':next_id, 'division':outcome['proposed_next_division'],
            'season_id':wire_season_id, 'status':'awaiting_native_initialization',
            'previous_cycle_id':before['cycle']['id'], 'initial_native_anchor':None}
        definition = json.loads((coordinator.account/'definition.json').read_bytes())
        from .season_choice_reference import snapshot as competition_reference
        if competition_reference(coordinator.stores()[0].definition) is not None or source.get('season_choice_handoff'):
            from .season_choice_pending import KEY,snapshot as pending_selection
            if competition_reference(coordinator.stores()[0].definition) is None:
                from .season_choice_reference import archive_unreferenced
                after['season_definition_history']=archive_unreferenced(coordinator.stores()[0].definition,after)
            after['cycle'][KEY]=pending_selection(source,after.get('season_definition_history'))
        else:
            definition['division_index'] = outcome['proposed_next_division']
            definition['season_id'] = wire_season_id
            images.append(coordinator._image('definition.json', encode(definition)))
    level_reward_images(before, source, images)
    return after, images


def level_quote(source):
    """XP-004 reward for the levels this source's report crossed, or None."""
    start = source.get('level_reward_start')
    if start is None:
        return None
    from .level_rewards import quote
    xp = source['native_xp_report']['quote']
    calculation = quote(start, xp['start']['level'], xp['after']['level'])
    return calculation if calculation['levels'] else None


def level_reward_images(before, source, images):
    """Pay level-ups inside the same profile/pack images (after match and title packs)."""
    calculation = level_quote(source)
    if calculation is None:
        return
    from .level_rewards import grant_images
    from .native_season_completion import encode
    profile = next(i for i in images if i['name'] == 'profile.json')
    packs = next((i for i in images if i['name'] == 'packs.json'), None)
    if packs is None:
        raise ValueError('Level rewards require the atomic pack image')
    profile_raw, packs_raw, record = grant_images(
        calculation, bytes.fromhex(profile['after']), bytes.fromhex(packs['after']),
        owner_id=source['id'], account_id=before['account_id'],
        persona_id=before['account_identity']['persona_id'], cycle_id=source['cycle_id'], encode=encode)
    profile['after'] = profile_raw.hex()
    packs['after'] = packs_raw.hex()
    source['level_reward'] = record


def validate_intent(coordinator, before, after, images):
    """Validate every staged/final image before the journal may apply any one."""
    old, new = before['active_match'], after['active_match']
    aborted=after.get('aborted_matches',[])[len(before.get('aborted_matches',[])):]
    if aborted:
        if len(aborted)!=1 or not old or not old.get('atomic_match') or images:
            raise ValueError('Invalid atomic abort intent')
        expected=copy.deepcopy(before);expected['prepared']=None
        retired=copy.deepcopy(old);retired.update(status='aborted',abort_reason='reauthenticated_before_match_commit')
        expected.setdefault('aborted_matches',[]).append(retired);expected['active_match']=None
        if after!=expected:raise ValueError('Atomic abort changes unrelated state')
        return True
    atomic_initialization=any(m.get('native_atomic_final') and m['cycle_id']==before['cycle'].get('previous_cycle_id') for m in before['matches'])
    if old is None and atomic_initialization and before['cycle']['status']=='awaiting_native_initialization' and after['cycle']['status']=='active':
        from .season_choice_pending import KEY
        if KEY in before['cycle']:raise ValueError('Next competition must be selected explicitly')
        current=after['cycle'].get('initial_native_anchor')
        from .local_seasons import CurrentSeason
        season,_=coordinator.stores()
        if not current or (current['round_number'],current['user_points'])!=(1,0):raise ValueError('Invalid atomic next-cycle initialization')
        CurrentSeason(**current).validate(season.definition)
        expected=copy.deepcopy(before);expected['prepared']=None
        expected['cycle'].update(status='active',initial_native_anchor=current)
        if after!=expected:raise ValueError('Initialization changes unrelated atomic state')
        if not images:
            # observe_initialization adopts a save already committed by the
            # ordinary SeasonStore path. It changes only the journal, never
            # rewrites that genuine save or grants a reward. Recheck the exact
            # persisted anchor during both preparation and crash recovery.
            actual=json.loads(season.path.read_bytes())
            if actual!={'persona_id':before['account_identity']['persona_id'],'current':current}:
                raise ValueError('Observed initialization differs from persisted native anchor')
            return True
        if len(images)!=1 or images[0]['name']!='seasons.json':raise ValueError('Initialization changes unrelated atomic state')
        image=images[0];prior=json.loads(bytes.fromhex(image['before']));final=json.loads(bytes.fromhex(image['after']))
        if prior!={'persona_id':before['account_identity']['persona_id'],'current':None} or final!={'persona_id':before['account_identity']['persona_id'],'current':current}:
            raise ValueError('Initialization does not preserve original native anchor')
        return True
    if not old or not old.get('atomic_match'):
        return False
    if new and new != old and new.get('native_xp_report') and not old.get('native_xp_report'):
        expected = copy.deepcopy(before)
        expected['prepared'] = None
        expected['active_match']['native_xp_report'] = new['native_xp_report']
        if after != expected or images or old['status'] != 'playing':
            raise ValueError('Atomic report changes unrelated state')
        validate_report(new, after)
        return True
    if new and new != old and new.get('atomic_end') and not old.get('atomic_end'):
        expected = copy.deepcopy(before)
        expected['prepared'] = None
        expected['active_match']['atomic_end'] = new['atomic_end']
        if after != expected or images:
            raise ValueError('Atomic End changes authoritative projections')
        validate_report(new, after)
        end_proposal(coordinator, after, new)
        return True
    added = after['matches'][len(before['matches']):]
    if not added:
        return False
    if len(added) != 1 or (not added[0].get('native_atomic_final') and (not old.get('atomic_end') or not added[0].get('native_atomic_save'))):
        raise ValueError('Atomic result requires its genuine native save')
    virtual=before
    from .atomic_pack_reference import compact
    pack_before=None
    from .training_expiry import before_image as training_before
    football_before=training_before(images)
    if old.get('atomic_pack') and compact(old['atomic_pack']):
        original=next((i for i in images if i['name']=='packs.json'),None)
        if original is None:raise ValueError('Compact pack intent missing before image')
        pack_before=bytes.fromhex(original['before'])
    if added[0].get('native_atomic_final'):
        virtual=copy.deepcopy(before)
        body=bytes.fromhex(added[0]['end_body_hex'])
        end=pure_end_proposal(coordinator,before,old,body)
        if not end['outcome']['complete']:raise ValueError('Atomic final End does not close season')
        virtual['active_match']['atomic_end']={'body_hex':body.hex(),'proposal':end}
        proposal={'current':None}
        expected,expected_images=final_state(coordinator,virtual,proposal,pack_before=pack_before,football_before=football_before)
    else:
        expected,expected_images=validated_save_state(coordinator,before,added[0],pack_before=pack_before,football_before=football_before)
    rollover=bool(added[0].get('native_atomic_final'))
    if rollover and not added[0].get('season_coin_start'):
        import uuid
        completion=after['completions'][-1]
        uuid.UUID(completion['id']);uuid.UUID(completion['next_cycle_id'])
        expected['completions'][-1].update(id=completion['id'],next_cycle_id=completion['next_cycle_id'])
        expected['cycle']['id']=completion['next_cycle_id']
    if after!=expected:raise ValueError('Atomic final journal differs from staged source')
    if len(images)!=len(expected_images):raise ValueError('Atomic image targets differ')
    by_name={i['name']:i for i in images}
    for image in expected_images:
        actual=by_name.get(image['name'])
        expected_before=pinned(old)[0] if image['name']=='profile.json' else pinned(old)[1] if image['name']=='seasons.json' else bytes.fromhex(image['before'])
        if image['name']=='packs.json':expected_before=pack_before if compact(old['atomic_pack']) else bytes.fromhex(old['atomic_pack']['packs_before_hex'])
        if image['name']=='definition.json':
            original=json.loads(bytes.fromhex(actual['before'])) if actual else {}
            check=dict(original);check.update(division_index=after['cycle']['division'],season_id=after['cycle']['season_id'])
            if (original.get('division_index')!=old['native_xp_start']['division'] or
                original.get('season_id')!=json.loads(pinned(old)[1])['current']['season_id'] or
                check!=json.loads(bytes.fromhex(image['after']))):
                raise ValueError('Atomic rollover definition mismatch')
            expected_before=bytes.fromhex(actual['before'])
        if actual is None or bytes.fromhex(actual['before'])!=expected_before or actual['after']!=image['after']:
            raise ValueError('Atomic profile/season image mismatch')
    validate_report(added[0],after)
    return True


def validated_save_state(coordinator,before,receipt,*,pack_before=None,football_before=None):
    old=before['active_match']
    saved=receipt['native_atomic_save']
    body = bytes.fromhex(saved['body_hex'])
    headers = {b'host':b'10.0.2.2:18081', b'x-ut-sid':b'fifa16-local-sid',
               b'content-length':str(len(body)).encode(), b'content-type':b'application/json'}
    # Validation must also work after some images were written. Parse against
    # the pinned BEFORE season/definition, never partially applied live files.
    from .local_seasons import SeasonStore, CurrentSeason
    from .offline_seasons_protocol import parse_season_save
    season, _ = coordinator.stores()
    from dataclasses import replace
    end = old['atomic_end']['proposal']
    from .season_choice_reference import resolve as source_definition
    definition = source_definition(season.definition, old, before.get('season_definition_history'))
    rollover = end['outcome']['complete']
    incoming_definition = replace(definition, division_index=end['outcome']['proposed_next_division']) if rollover else definition
    class PinnedSeason(SeasonStore):
        def load(self):
            value = json.loads(pinned(old)[1])['current']
            return None if rollover else CurrentSeason(**value)
    current = parse_season_save(body, PinnedSeason(season.path, incoming_definition)).validate(incoming_definition)
    target = f'/ut/game/fifaworldmobile/season/{incoming_definition.season_id}/division/{11-incoming_definition.division_index}/user'
    if saved['target'] != target:
        raise ValueError('Atomic save route differs')
    if rollover:
        if (current.round_number, current.user_points) != (1, 0):
            raise ValueError('Invalid atomic rollover anchor')
    elif (current.round_number, current.user_points) != (end['observation']['expected_round'], end['observation']['expected_points']):
        raise ValueError('Atomic save differs from staged result')
    proposal = {'save':saved, 'current':asdict(current)}
    return final_state(coordinator,before,proposal,pack_before=pack_before,football_before=football_before)
