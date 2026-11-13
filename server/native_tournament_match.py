"""Captured tournament lifecycle with separate source-bound reward admission.

Version 1 is certified; the isolated version 2 candidate stages a genuine
GameReport and commits matching End rewards through the same recovery journal.
The original client owns bracket generation and every reported result.
"""
import hashlib,json
from pathlib import Path
from .game_auth import SID
from .native_tournament_state import load,CUPS,path_for

PATH='/ut/game/fifaworldmobile/match/sim'
REWARDS=None  #explicit revival policy; None = reward-free (default)
REWARD_VERSION='tournament_championship_rewards_v1'


def configure_rewards(path=None):
    global REWARDS
    REWARDS=None
    if path is None:return
    value=json.loads(Path(path).read_bytes())
    if value.get('version') == 'tournament_rewards_v2':
        from .tournament_reward_policy import load_policy
        REWARDS = load_policy(path)
        return
    if (value.get('version')!=REWARD_VERSION or value.get('classification')!='revival_policy_temporary' or
            set(value.get('coins',{}))!={'201','202','203','204'} or
            any(type(v) is not int or not 0<v<=10**6 for v in value['coins'].values()) or
            value.get('packs')!='disabled' or value.get('retroactive') is not False):raise ValueError('Invalid tournament reward policy')
    REWARDS=value
PLAYED='/ut/game/fifaworldmobile/match'  #1369 genuine tournament PLAY MATCH Create


def inspect_create(method,target,headers,body,account):
    if (method!='POST' or target not in (PATH,PLAYED) or headers.get(b'host')!=b'10.0.2.2:18081' or
            headers.get(b'x-ut-sid')!=SID.encode() or headers.get(b'content-type')!=b'application/json' or
            headers.get(b'content-length')!=str(len(body)).encode()):raise ValueError('Not captured tournament CreateSim')
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('Duplicate tournament CreateSim field')
            value[key]=item
        return value
    value=json.loads(body,object_pairs_hook=unique)
    fields={'squadId','type','tournamentId','customData1'}
    if (type(value) is not dict or set(value) not in (fields,fields|{'tournamentTrophyRound'}) or
            any(type(value[k]) is not int for k in ('squadId','tournamentId','customData1')) or
            value['type']!='OFFLINE' or value['customData1']!=0):raise ValueError('Unmapped tournament CreateSim fields')
    if value['tournamentId'] not in CUPS:raise ValueError('Unknown tournament')
    saved=load(account,value['tournamentId'])
    if saved is None or value['tournamentId']!=saved['tournament_id']:raise ValueError('Tournament source mismatch')
    if closed(account,saved) is not None:raise ValueError('Tournament run closed')
    #1365 final CreateSim adds the literal string "true". It is not a
    #reward authorization; bind it to the saved native final checkpoint.
    if ('tournamentTrophyRound' in value) != (saved['round']==4) or (
            'tournamentTrophyRound' in value and value['tournamentTrophyRound']!='true'):
        raise ValueError('Tournament final marker/checkpoint mismatch')
    from .local_football import FootballStore
    from .local_squads import active_record,wire_id
    football=FootballStore(Path(account)/'football.json').load(1)
    if value['squadId']!=wire_id(active_record(football)):raise ValueError('Tournament squad mismatch')
    owned={item.instance_id for item in football.owned_items}
    starters=[slot.instance_id for slot in football.active_lineup if slot.index<11]
    if len(starters)!=11 or len(set(starters))!=11 or not set(starters)<=owned:raise ValueError('Tournament requires owned starting11')
    from .offline_tournaments import eligibility
    from .native_tournament_catalog import cup_for
    cup = cup_for(account, saved['tournament_id'])
    if not eligibility(cup,football)['eligible']:raise ValueError('Ineligible tournament squad')
    identity=f"tournament-initial-sim-v1:{saved.get('run_id',saved['request_sha256'])}:{saved['tournament_id']}:{saved['round']}"
    quote={'classification':'captured_tournament_create_sim_inspection_only',
            'source_id':hashlib.sha256(identity.encode()).hexdigest(),
            'tournament_id':saved['tournament_id'],'round':saved['round'],
            'checkpoint_sha256':saved['request_sha256'],'request_sha256':hashlib.sha256(body).hexdigest(),
            'squad_id':value['squadId'],'starting11':starters,
            'ack_enabled':False,'progression_enabled':False,'rewards_enabled':False}
    if target==PLAYED:quote['kind']='played'  #Sim quotes stay byte-compatible
    return quote

#Isolated discovery ledger: source binding only. No wallet/item effects.
from .account_transaction import account_locked,atomic
from .identity import json_response
LEDGER='native-tournament-sim.json'


def ledger(account):
    path=Path(account)/LEDGER
    if not path.exists():return {'version':'native_tournament_sim_v1','active':None}
    value=json.loads(path.read_bytes())
    if not {'version','active'}<=set(value) or set(value)-{'version','active','prepared','last','trophy_counts','counted_source','forfeited','closed','forfeits','abandoned'} or value['version']!='native_tournament_sim_v1':raise ValueError('Unknown tournament match journal')
    return value


@account_locked
def proposal(method,target,headers,body,account):
    if (target not in (PATH,PATH+'/end',PLAYED,PLAYED+'/end') or headers.get(b'host')!=b'10.0.2.2:18081' or
            headers.get(b'x-ut-sid')!=SID.encode() or headers.get(b'content-type')!=b'application/json' or
            headers.get(b'content-length')!=str(len(body)).encode()):raise ValueError('Unmapped tournament match framing')
    recover(account)
    value=ledger(account);source=value['active'];digest=hashlib.sha256(body).hexdigest()
    session=headers.get(b'x-fifa-local-original-sid',headers[b'x-ut-sid']).decode('ascii')
    played=target in (PLAYED,PLAYED+'/end')
    if method=='POST' and target in (PATH,PLAYED):
        quote=inspect_create(method,target,headers,body,account)
        if source and source['quote']!=quote:
            #1372: concurrent cups. A result-free (no End) source of another
            #fixture is abandoned by the stock client; it never carries a result.
            if source['phase'] not in ('created','playing') or source['end_sha256'] or value.get('prepared'):
                raise ValueError('Tournament match already pending')
            value['abandoned']=value.get('abandoned',0)+1;source=value['active']=None
        if source:
            if source['session']!=session:
                if source['phase'] not in ('created','playing') or source['end_sha256']:raise ValueError('Tournament match already pending')
                #1370: after an interrupted played match (connection lost) the
                #stock client sends no End and reloads the same round from the
                #server checkpoint. A new session supersedes the result-free
                #source for the same fixture; a source with an End never does.
                if source['phase']=='playing':source['restarts']=source.get('restarts',0)+1
                source.update(session=session,phase='created',play_sha256=None)
                # A staged GameReport without an accepted End granted nothing
                # (1391: End refused, client left the match); the replayed
                # round reports again for the same source identity.
                source.pop('xp_report', None)
        else:
            from .tournament_account import context as account_context
            _, active_match, prepared = account_context(account)
            if active_match or prepared:
                raise ValueError('Pending Seasons match')
            value['active']={'quote':quote,'session':session,'phase':'created','play_sha256':None,'end_sha256':None,'end_body_hex':None}
            if REWARDS is not None and REWARDS.get('version') == 'tournament_rewards_v2':
                from .tournament_reward_policy import snapshot
                profile = json.loads((Path(account) / 'profile.json').read_bytes())
                saved = load(account, quote['tournament_id'])
                trophies = value.get('trophy_counts', {}).get(str(quote['tournament_id']), 0)
                from .native_tournament_catalog import cup_for
                cup = cup_for(account, quote['tournament_id'])
                value['active']['reward_start'] = snapshot(
                    quote['tournament_id'], cup.difficulty,
                    profile.get('revival_total_xp') or 0, trophies,
                )
                value['active']['reward_run_id'] = saved.get('run_id', saved['request_sha256'])
                from . import level_rewards
                if level_rewards.enabled(account):
                    value['active']['level_reward_start'] = level_rewards.start()
            if played:
                import time
                value['active']['create_response']={'startDateTime':int(time.time())}
        return value
    last=value.get('last',{})
    if method=='PUT' and target in (PATH+'/end',PLAYED+'/end') and last.get('end_sha256')==digest:return value
    if not source or source['session']!=session:raise ValueError('No current tournament match source')
    if (source['quote'].get('kind')=='played')!=played:raise ValueError('Tournament match kind/route mismatch')
    from .local_football import FootballStore
    football=FootballStore(Path(account)/'football.json')
    if method=='PUT' and target in (PATH,PLAYED):
        if source['phase'] not in ('created','playing'):raise ValueError('Tournament match ended')
        if played and source['phase']=='playing' and source['play_sha256'] not in (None,digest):
            #In-match substitution: same captured played validator as Seasons; no state.
            from .play_game import response_for as substitution_ack
            if substitution_ack(method,target,headers,body,football,allow_substitutions=True) is None:raise ValueError('Wrong tournament substitution')
            return value
        if played:
            from .native_played_protocol import play_ack
        else:
            from .native_simulation_protocol import play_ack
        stale = None
        if play_ack(method,target,headers,body,football,enabled=True) is None:
            stale = None if played else _pre_edit_lineup(account, headers, body, football)
            if stale is None:
                raise ValueError('Unmapped tournament PlaySim')
        players=json.loads(body)['items'];starting=set(source['quote']['starting11'])
        if stale is not None:
            # 1577: genuine Sim PlaySim carries the lineup a same-session squad
            # save replaced. Keep it on the source; the End stays exact.
            source['play_lineup'] = stale
        elif not starting<=set(item['id'] for item in players):
            raise ValueError('Tournament starting squad changed')
        if source['play_sha256'] not in (None,digest):raise ValueError('Conflicting tournament PlaySim')
        source.update(phase='playing',play_sha256=digest);return value
    if method=='PUT' and target in (PATH+'/end',PLAYED+'/end'):
        if source['phase'] not in ('playing','ended'):raise ValueError('Tournament simulation not started')
        if source['phase'] == 'ended' and source['end_sha256'] == digest:
            return value
        from .destroy_match import response_for,PATH as END
        if response_for(method,END,headers,body,football) is None:raise ValueError('Unmapped tournament native result')
        result=json.loads(body);ours=result['myMatchStats']['goals'];theirs=result['opponentMatchStats']['goals']
        if source.get('reward_start') is not None and result['endReason'] == 'DRAW':
            raise ValueError('Native tournament draw/penalty completion is not captured')
        if (result['endReason'] not in ('WIN','LOSS','DRAW') or type(ours) is not int or type(theirs) is not int or not 0<=ours<=99 or not 0<=theirs<=99):raise ValueError('Unmapped tournament outcome')
        if source['end_sha256'] not in (None,digest):raise ValueError('Conflicting tournament End')
        source.update(phase='ended',end_sha256=digest,end_body_hex=body.hex())
        reward_intent = None
        if source.get('reward_start') is not None:
            from .tournament_reward_images import prepare
            outcome = {'WIN': 'W', 'LOSS': 'L', 'DRAW': 'D'}[result['endReason']]
            report = source.get('xp_report')
            shootout = None
            # 1391 genuine: GameReport MatchDraw (0-0) then End WIN with equal
            # goals = tie decided on penalties. Pay the drawn match; the End's
            # reason decides advancement/elimination/title.
            if (report is not None and report['observation']['result'] == 'D'
                    and outcome in ('W', 'L') and ours == theirs):
                shootout, outcome = outcome, 'D'
            if (
                report is None or report['observation']['result'] != outcome
                or report['observation']['score'] != [ours, theirs]
                or result['matchDifficulty'] != source['reward_start']['difficulty']
            ):
                raise ValueError('Tournament End contradicts or lacks its source-bound GameReport')
            reward_intent = prepare(account, source, outcome, shootout)
            source['reward_receipt'] = reward_intent['receipt']
        #1366/1371: no client save follows a final WIN or any LOSS; close the
        #run in this same journal write (trophy exactly once) and free the slot.
        completion=('trophy_round_win' if result['endReason']=='WIN' and source['quote']['round']==4 else
                    'eliminated' if result['endReason']=='LOSS' else None)
        if completion:
            close_run(value, source, completion, account=None if reward_intent else account)
            if reward_intent:
                value['last']['reward_receipt'] = reward_intent['receipt']
        if reward_intent:
            value['prepared'] = reward_intent
        return value
    raise ValueError('Unsupported tournament match operation')


def _pre_edit_lineup(account, headers, body, football):
    """Return the same-session replaced lineup a captured-shape PlaySim names."""
    from .local_football import club_manager_ids
    try:
        value = json.loads(body)
    except ValueError:
        return None
    items = value.get('items') if type(value) is dict and set(value) == {'items'} else None
    if type(items) is not list or len(items) not in (11, 12):
        return None
    if any(type(item) is not dict or set(item) != {'id'} or type(item['id']) is not int for item in items):
        return None
    state = football.load(1)
    owned = {item.instance_id for item in state.owned_items} | club_manager_ids(state)
    from .squad_lineup_history import replaced_match
    return replaced_match(account, headers, [item['id'] for item in items], owned)


@account_locked
def response_for(method,target,headers,body,account,*,commit=False):
    ended=None
    if commit and method=='PUT' and target in (PATH+'/end',PLAYED+'/end'):
        try:ended=ledger(account).get('active')
        except (ValueError,OSError):ended=None
    try:value=proposal(method,target,headers,body,account)
    except (ValueError,KeyError,TypeError,OSError,UnicodeError):return None
    if commit:
        path=Path(account)/LEDGER;raw=(json.dumps(value,indent=2,sort_keys=True)+'\n').encode()
        if not path.exists() or path.read_bytes()!=raw:atomic(path,raw)
        if value.get('prepared'):recover(account)
        if method=='PUT' and target in (PATH+'/end',PLAYED+'/end') and ended is not None:
            #CLUB-005: count this match's appearances/goals once (display stats).
            #The source may already be closed (final/elimination), so use the
            #pre-commit source and this End body.
            done=value.get('active') or value.get('last') or {}
            done_id=done.get('source_id') or done.get('quote',{}).get('source_id')
            if done.get('end_sha256')==hashlib.sha256(body).hexdigest() and done_id==ended['quote']['source_id']:
                from .item_history import record_match
                from .tournament_match_report import identity
                record_match(account,ended['quote']['source_id'],identity(ended),body)
                # ACCOMP-001: one committed tournament match (result from its reward receipt).
                from .accomplishments import record_tournament_match
                record_tournament_match(account,ended['quote']['source_id'],identity(ended),
                                        done.get('reward_receipt'))
    if method=='POST' and target==PLAYED:
        #010335cc consumes startDateTime; stored so exact retries match.
        return json_response(value['active']['create_response'])
    if method == 'PUT' and target in (PATH + '/end', PLAYED + '/end'):
        source = value.get('active')
        receipt = source.get('reward_receipt') if source else value.get('last', {}).get('reward_receipt')
        if receipt and receipt['end_sha256'] == hashlib.sha256(body).hexdigest():
            from .tournament_reward_images import awards_reply
            return json_response(awards_reply(receipt))
    return json_response({})


@account_locked
def recover(account):
    from .account_transaction import recover_images
    value=ledger(account);intent=value.get('prepared')
    if intent is None:return
    if intent.get('kind') == 'tournament_rewards_v2':
        from .tournament_reward_images import validate
        intent = validate(intent)
        receipt = intent['receipt']
        source = value.get('active')
        owner = source if source is not None else value.get('last', {})
        source_id = source['quote']['source_id'] if source else owner.get('source_id')
        if (
            owner.get('reward_receipt') != receipt
            or source_id != receipt['source_id']
            or owner.get('end_sha256') != receipt['end_sha256']
        ):
            raise ValueError('Tournament reward intent lost its source')
        recover_images(Path(account), intent['images'])
        value['prepared'] = None
        atomic(Path(account) / LEDGER, (json.dumps(value, indent=2, sort_keys=True) + '\n').encode())
        return
    if intent.get('kind')=='championship_reward':
        record=intent.get('receipt')
        if (set(intent)!={'kind','images','receipt'} or len(intent['images'])!=1 or intent['images'][0]['name']!='profile.json' or
                value.get('last')!=record or value.get('closed',{}).get(str(record['tournament_id']))!=record or
                record.get('completion')!='trophy_round_win'):raise ValueError('Invalid tournament reward intent')
        image=intent['images'][0]
        before=json.loads(bytes.fromhex(image['before']));after=json.loads(bytes.fromhex(image['after']))
        if after!={**before,'credits':before.get('credits',0)+record['coins']}:raise ValueError('Tournament reward image mismatch')
        recover_images(Path(account),intent['images'])
        value['prepared']=None
        atomic(Path(account)/LEDGER,(json.dumps(value,sort_keys=True,indent=2)+'\n').encode());return
    if (set(intent)!={'images','receipt'} or len(intent['images'])!=1 or
            intent['images'][0]['name'] not in {path_for(account,t).name for t in CUPS} or not value['active'] or
            value['active']['phase']!='ended' or intent['receipt']['source_id']!=value['active']['quote']['source_id']):raise ValueError('Invalid tournament recovery intent')
    recover_images(Path(account),intent['images'])
    value.update(active=None,prepared=None,last=intent['receipt'])
    atomic(Path(account)/LEDGER,(json.dumps(value,sort_keys=True,indent=2)+'\n').encode())


@account_locked
def save_preview(account,body,tournament_id):
    recover(account)
    from .native_tournament_state import checkpoint,load
    value=ledger(account);digest=hashlib.sha256(body).hexdigest()
    if value.get('last',{}).get('save_sha256')==digest:return None
    source=value['active'];before=load(account,tournament_id)
    #State-based idempotency: the exact checkpoint already stored for this cup
    #(stale retry after later operations) gets the same SUCCESS, no writes.
    if before is not None and before['request_sha256']==digest:return None
    if not source or source['phase']!='ended' or not before:raise ValueError('No ended tournament source')
    if source['quote']['tournament_id']!=tournament_id:raise ValueError('Tournament source/cup mismatch')
    if source['quote']['checkpoint_sha256']!=before['request_sha256']:raise ValueError('Tournament checkpoint changed')
    outcome=json.loads(bytes.fromhex(source['end_body_hex']))
    if outcome['endReason']!='WIN':raise ValueError('Elimination/forfeit checkpoint not mapped')
    #1366 genuine final WIN sends no save; never admit a speculative round5 PUT.
    if source['quote']['round']==4:raise ValueError('No captured post-final tournament save')
    parsed,raw=checkpoint(body,tournament_id)
    if parsed['round']!=before['round']+1 or int.from_bytes(raw[4:8],'little')!=parsed['round']-1:raise ValueError('Tournament round/source disagreement')
    return dict(version='native_tournament_progress_v1',tournament_id=tournament_id,round=parsed['round'],
        tournamentData=parsed['tournamentData'],request_sha256=digest,source_id=source['quote']['source_id'],prior_checkpoint_sha256=before['request_sha256'],run_id=before.get('run_id',before['request_sha256']))


@account_locked
def commit_save(account,body,tournament_id):
    candidate=save_preview(account,body,tournament_id)
    if candidate is None:return
    path=path_for(account,tournament_id);value=ledger(account)
    image={'name':path.name,'before':path.read_bytes().hex(),'after':(json.dumps(candidate,sort_keys=True,indent=2)+'\n').encode().hex()}
    receipt = {
        'save_sha256': candidate['request_sha256'],
        'source_id': candidate['source_id'],
        'end_sha256': value['active']['end_sha256'],
        'round': candidate['round'],
    }
    if value['active'].get('reward_receipt') is not None:
        receipt['reward_receipt'] = value['active']['reward_receipt']
    value['prepared'] = {'images': [image], 'receipt': receipt}
    atomic(Path(account)/LEDGER,(json.dumps(value,sort_keys=True,indent=2)+'\n').encode());recover(account)


def close_run(value,source,completion,*,account=None):
    quote=source['quote'];key=str(quote['tournament_id'])
    record={'tournament_id':quote['tournament_id'],'save_sha256':quote['checkpoint_sha256'],'source_id':quote['source_id'],
            'end_sha256':source['end_sha256'],'round':quote['round'],'completion':completion}
    new_trophy=completion=='trophy_round_win' and value.get('counted_source')!=quote['source_id']
    if (
        new_trophy and REWARDS is not None and account is not None
        and REWARDS.get('version') == REWARD_VERSION
    ):
        #Revival policy (user 3 Nov): coins once per genuine championship, in the
        #same prepared journal write as the closure; profile image applied after.
        from .local_profile import validate_credits
        path=Path(account)/'profile.json';raw=path.read_bytes();profile=json.loads(raw)
        coins=REWARDS['coins'][key];before=validate_credits(profile.get('credits',0))
        after=dict(profile);after['credits']=validate_credits(before+coins)
        record.update(coins=coins,credits_before=before,credits_after=after['credits'],policy=REWARDS['version'])
        value['prepared']={'kind':'championship_reward','receipt':record,
            'images':[{'name':'profile.json','before':raw.hex(),'after':(json.dumps(after,indent=2,sort_keys=True)+'\n').encode().hex()}]}
    value.setdefault('closed',{})[key]=record
    if new_trophy:
        counts=value.setdefault('trophy_counts',{});counts[key]=counts.get(key,0)+1;value['counted_source']=quote['source_id']
    value.update(active=None,last=record)


def legacy_terminal(saved,value):
    """Archived journals (before 1372) kept a terminal End in 'active'."""
    source=value.get('active')
    if not saved or not source or source.get('phase')!='ended' or not source.get('end_body_hex'):return None
    quote=source['quote']
    if (quote['tournament_id']!=saved['tournament_id'] or quote['checkpoint_sha256']!=saved['request_sha256'] or
            quote['round']!=saved['round']):return None
    reason=json.loads(bytes.fromhex(source['end_body_hex'])).get('endReason')
    if reason=='WIN' and quote['round']==4:return 'trophy_round_win',source
    if reason=='LOSS':return 'eliminated',source
    return None


def closure(saved,value):
    """Terminal record for exactly this saved run, eager or legacy-derived."""
    if not saved:return None
    rec=value.get('closed',{}).get(str(saved['tournament_id']))
    if rec and rec['save_sha256']==saved['request_sha256']:return rec
    legacy=legacy_terminal(saved,value)
    if legacy:
        completion,source=legacy
        return {'tournament_id':saved['tournament_id'],'save_sha256':saved['request_sha256'],'source_id':source['quote']['source_id'],
                'end_sha256':source['end_sha256'],'round':saved['round'],'completion':completion,'legacy':True}
    return None


def completed_final(account,saved=None,value=None):
    saved=load(account) if saved is None else saved
    value=ledger(account) if value is None else value
    rec=closure(saved,value)
    return rec if rec and rec['completion']=='trophy_round_win' else None


def eliminated(account,saved=None,value=None):
    saved=load(account) if saved is None else saved
    value=ledger(account) if value is None else value
    rec=closure(saved,value)
    return rec if rec and rec['completion']=='eliminated' else None


def pending_legacy_trophy(saved,value):
    rec=closure(saved,value)
    return bool(rec and rec.get('legacy') and rec['completion']=='trophy_round_win' and value.get('counted_source')!=rec['source_id'])


@account_locked
def settle(account,saved):
    """Before a new run of the same cup: move a legacy terminal source out of
    'active' (counting a legacy trophy once). Eager closures need nothing."""
    value=ledger(account);rec=closure(saved,value)
    if not rec or not rec.get('legacy'):return
    rec=dict(rec);rec.pop('legacy')
    source=value['active'];close_run(value,source,rec['completion'])
    atomic(Path(account)/LEDGER,(json.dumps(value,sort_keys=True,indent=2)+'\n').encode())


def forfeited(account,saved=None,value=None):
    """True when exactly this saved run was withdrawn by the captured DELETE."""
    saved=load(account) if saved is None else saved
    value=ledger(account) if value is None else value
    if not saved:return False
    receipts=[value.get('forfeits',{}).get(str(saved['tournament_id'])),value.get('forfeited')]
    return any(r and r.get('save_sha256')==saved['request_sha256'] for r in receipts)


def forfeit_preview(account,method,target,headers,body):
    """1368 original FORFEIT→YES: DELETE /tournament/user/{id}, empty body.

    Quit response parser (file0x230064c) ignores the body and returns success;
    only a 200 is consumed. No trophy, wallet, item or XP effects.
    """
    prefix='/ut/game/fifaworldmobile/tournament/user/'
    if (method!='DELETE' or not target.startswith(prefix) or body or
            headers.get(b'host')!=b'10.0.2.2:18081' or headers.get(b'x-ut-sid')!=SID.encode() or
            headers.get(b'content-length',b'0')!=b'0'):raise ValueError('Not the captured tournament forfeit')
    tail=target[len(prefix):]
    if not tail.isdigit() or str(int(tail))!=tail or int(tail) not in CUPS:raise ValueError('Invalid tournament id')
    tournament_id=int(tail);saved=load(account,tournament_id);value=ledger(account)
    if saved is None:raise ValueError('No saved tournament to forfeit')
    receipt={'save_sha256':saved['request_sha256'],'tournament_id':tournament_id,'round':saved['round'],
             'run_id':saved.get('run_id',saved['request_sha256'])}
    if receipt in (value.get('forfeits',{}).get(str(tournament_id)),value.get('forfeited')):return value,None  #exact retry
    if forfeited(account,saved,value):raise ValueError('Conflicting forfeit receipt')
    active=value.get('active')
    if value.get('prepared') is not None or (active is not None and active['quote']['tournament_id']==tournament_id):
        raise ValueError('Tournament match pending; forfeit unmapped')
    if closure(saved,value) is not None:raise ValueError('Closed tournament; forfeit unmapped')
    return value,receipt


@account_locked
def commit_forfeit(account,method,target,headers,body):
    value,receipt=forfeit_preview(account,method,target,headers,body)
    if receipt is None:return
    value.setdefault('forfeits',{})[str(receipt['tournament_id'])]=receipt
    atomic(Path(account)/LEDGER,(json.dumps(value,sort_keys=True,indent=2)+'\n').encode())


def closed(account,saved=None,value=None):
    """'completed', 'eliminated', 'forfeited' or None for exactly this run."""
    saved=load(account) if saved is None else saved
    value=ledger(account) if value is None else value
    rec=closure(saved,value)
    if rec:return 'completed' if rec['completion']=='trophy_round_win' else 'eliminated'
    if forfeited(account,saved,value):return 'forfeited'
    return None
