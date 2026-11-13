"""Captured tournament catalog, checkpoints and lifecycle dispatch.

The certified version 1 admission and isolated version 2 reward extension stay
separate. Typed native readers own the DTOs; local policy owns chosen prizes.
"""
import json
from pathlib import Path
from .game_auth import SID
from .identity import json_response
from .offline_tournaments import PATH,load_catalog,draw_clubs

ROOT=Path(__file__).resolve().parents[1]
ACCOUNT=CATALOG=None
START=SIM=False
LIST='/ut/game/fifaworldmobile/tournament/list?active=true&count=99'
USER_LIST='/ut/game/fifaworldmobile/tournament/user/list'
TEAMS='/ut/game/fifaworldmobile/tournament/teams?groupId=0&count=15'


def configure(account=None,policy_path=PATH,*,start=False,sim=False,rewards=None):
    global ACCOUNT,CATALOG,START,SIM
    ACCOUNT=CATALOG=None;START=SIM=False
    from .native_tournament_match import configure_rewards
    configure_rewards(None)
    if rewards is not None and not sim:raise ValueError('Tournament rewards require source-bound Sim/played lifecycle')
    if sim and not start:raise ValueError("Tournament Sim requires initial checkpoint mode")
    if type(start) is not bool or (start and account is None):raise ValueError("Explicit isolated tournament Start requires catalog")
    if account is None:return
    account=Path(account).resolve()
    from . import tournament_release
    from .fresh_account_runtime import selected as fresh_selected
    if account==tournament_release.REAL:
        #GAME-012 certified normal admission: marker+backup+certificate, and the
        #exact certified catalog and reward policies (rewards are mandatory here).
        if not (start and sim and rewards is not None):raise ValueError('Normal tournaments require the certified full lifecycle')
        tournament_release.admit(account,policy_path,rewards)
    elif not fresh_selected(account) and (ROOT/'reports' not in account.parents or account.name!='isolated-account' or
            not (account/'.lab-snapshot.json').is_file()):raise ValueError('Uncertified tournaments require archived isolation')
    CATALOG=load_catalog(policy_path);ACCOUNT=account;START=start;SIM=sim
    configure_rewards(rewards)


def rules(cup):
    rows=[]
    def rule(*pairs):rows.append({'rule':[{'type':kind,'data':value} for kind,value in pairs]})
    if cup.required_quality:
        #010181a4 compares each selected player's quality;010128b4 scope2==.
        #01012688 applyTo0/1 selects starters+subs.01040678 owns wire enums.
        #1350physically maps quality1→Bronze;0renders blank. PlayerCount is
        #a named-group predicate, not a standalone size caption. Backend keeps
        #the18-owned-player guard; do not emit that misleading native rule.
        rule(('playerQuality',{'bronze':1,'silver':2,'gold':3}[cup.required_quality]),
            ('scope',2),('applyTo',0),('applyTo',1))
    if cup.minimum_chemistry:rule(('teamChemistry',cup.minimum_chemistry),('scope',0))
    if cup.minimum_brazilian_starters:
        #01019adc counts players matching nationId; scope0 is >= and applyTo0
        #selects the starting XI. nationCount counts distinct nations instead.
        rule(
            ('playerCount', cup.minimum_brazilian_starters),
            ('nationId', 54), ('scope', 0), ('applyTo', 0),
        )
    return rows


def listing():
    counts={}
    if START:
        from .native_tournament_state import load_all
        from .native_tournament_match import ledger,pending_legacy_trophy
        journal=ledger(ACCOUNT);counts=dict(journal.get('trophy_counts',{}))
        for saved in load_all(ACCOUNT).values():
            if pending_legacy_trophy(saved,journal):
                key=str(saved['tournament_id']);counts[key]=counts.get(key,0)+1
    result = {'tournament':[dict(id=c.service_id,type='offline',treeType='knockout',
        numTeams=16,numRounds=4,matchlength=6,aigroup=0,trophyResourceId=c.metadata_service_id,
        trophyUserCount=counts.get(str(c.service_id),0),unlockreq=0,lock='UNLOCKED',triesMax=0,triesPeriod=0,triesRemaining=-1,
        starttime=0,endtime=0x7fffffff,visStart=0,visEnd=0x7fffffff,
        timeUntilStart=0,timeUntilEnd=0x7fffffff,nextReset=0,
        eligibilityOperation='AND',elgReq=rules(c),awardSet={'awards':[]},
        rounds=[dict(id=i,difficulty=c.difficulty,coins=0,rewardMultiplier=0) for i in range(1,5)])
        for c in CATALOG.values()]}
    from .native_tournament_match import REWARDS
    if REWARDS is not None and REWARDS.get('version') == 'tournament_rewards_v2':
        for cup in result['tournament']:
            cup['awardSet'] = {'awards': bonus_awards(cup['id'], counts)}
    return result


def bonus_awards(cup_id, counts):
    """Native TOURNAMENT BONUS records for one cup (presentation only).

    010405c0 reads integer awardType/value/halid. Type 1 is the coin scalar
    (physically verified 1378). Type 2 is a reward pack (1384): the original
    Lua labels it with the fixed LTXT_MOB_POSTMATCH_REWARD_PACK strings and
    takes only the icon from GetRewardPackInfo(halid), so halid is the pack's
    native caption-bank key. First-win packs are shown only while the cup has
    no trophy, matching the payout rule (prior_trophies == 0 at the final).
    """
    from .native_tournament_match import REWARDS

    prize = REWARDS['championship'][str(cup_id)]
    awards = [{'awardType': 1, 'value': prize['coins'], 'halid': 0}]
    if counts.get(str(cup_id), 0) != 0:
        return awards
    keys = reward_pack_keys()
    if keys is None:
        return awards
    for definition in prize['first_win_packs']:
        # Type 3 (items) is labelled natively as AWARD_LABEL_<halid> from the
        # shipped string table (1386 rendered "*AWARD_LABEL_1879228136"), so a
        # player prize cannot be named without asset changes. Every prize is
        # an unopened pack/envelope and is presented as type 2; the stock
        # panel shows one pack slot (1385: only the first type-2 record).
        awards.append({'awardType': 2, 'value': 1, 'halid': keys[definition]})
    return awards


def reward_pack_keys():
    """Caption-bank key per definition, or None without the native pack bank."""
    from . import native_pack_sessions as sessions

    if ACCOUNT is None or sessions.ACCOUNT != ACCOUNT:
        return None
    names = sessions.definitions()
    return {name: sessions.FIRST + index * sessions.SLOTS for index, name in enumerate(names)}


def cup_for(account, tournament_id):
    selected = CATALOG if ACCOUNT is not None and Path(account).resolve() == ACCOUNT else load_catalog()
    cup = next((cup for cup in selected.values() if cup.service_id == tournament_id), None)
    if cup is None:
        raise ValueError('Unknown selected tournament')
    return cup


def metadata(cup):
    #0100a640 tournamentType<4 generates TOURNAMENT_LOC_<id>;4/5 are Seasons.
    return dict(tournamentId=cup.service_id,tournamentType=0,assetName=cup.trophy_asset,
        silName=cup.trophy_silhouette,locString=[dict(lang='eng_us',label=cup.name)])


MATCH_PATHS=('/ut/game/fifaworldmobile/match/sim','/ut/game/fifaworldmobile/match/sim/end',
             '/ut/game/fifaworldmobile/match','/ut/game/fifaworldmobile/match/end')


def response_for(method,target,headers,body,account):
    if ACCOUNT is None or account is None or Path(account).resolve()!=ACCOUNT:return None
    # All account reads pass this adapter before wallet/inventory projections.
    # Finish a previously prepared tournament operation before exposing either.
    if START:
        from .native_tournament_match import recover
        recover(ACCOUNT)
    from .native_tournament_match import REWARDS
    if REWARDS is not None and REWARDS.get('version') == 'tournament_rewards_v2':
        from .tournament_match_report import response_for as report_reply
        response = report_reply(method, target, headers, body, ACCOUNT)
        if response is not None:
            return response
    if START:
        #Complete any prepared tournament reward before any read (e.g. credits).
        from .native_tournament_match import recover
        recover(ACCOUNT)
    if SIM and target in MATCH_PATHS:
        from .native_tournament_match import response_for as match_reply
        candidate=match_reply(method,target,headers,body,account)
        if candidate is not None:return candidate
    cup_id=next((c.service_id for c in CATALOG.values() if target==f'/ut/game/fifaworldmobile/tournament/user/{c.service_id}'),None)
    if method=='DELETE' and cup_id is not None and START:
        from .native_tournament_match import forfeit_preview
        try:
            forfeit_preview(ACCOUNT,method,target,headers,body)
            return json_response({})
        except (ValueError,TypeError,KeyError,OSError):return None
    if method=='PUT' and cup_id is not None and START:
        try:
            save_request(method,target,headers,body,account)
            return json_response({'result':'SUCCESS'})
        except (ValueError,TypeError,KeyError,OSError):return None
    if (method!='GET' or body or headers.get(b'host')!=b'10.0.2.2:18081' or
            headers.get(b'content-length',b'0')!=b'0'):return None
    if target==LIST and headers.get(b'x-ut-sid')==SID.encode():return json_response(listing())
    if START and cup_id is not None and headers.get(b'x-ut-sid')==SID.encode():
        #1356 genuine cold GET;02310258 consumes round + encoded tournamentData.
        from .native_tournament_state import load
        try:saved=load(ACCOUNT,cup_id)
        except (ValueError,TypeError,KeyError,OSError):return None
        if saved is not None and saved['tournament_id']==cup_id:
            #A completed final is no longer resumable; never serve its stale
            #round4 checkpoint. Unmapped post-completion loads stay held.
            from .native_tournament_match import closed
            try:
                if closed(ACCOUNT,saved) is not None:return None
            except (ValueError,TypeError,KeyError,OSError):return None
            return json_response({k:saved[k] for k in ('round','tournamentData')})
        return None
    if target==TEAMS and headers.get(b'x-ut-sid')==SID.encode():
        #1353 genuine GET;01034bc0 consumes numeric teamId[] only.
        #All preview cups explicitly use local group0: one deterministic supplied
        #opponent pool, not a recovered EA group. Client generates the bracket.
        #User revival choice (3 November): randomise the opponent draw per new
        #run. The client builds/saves its own bracket from this list, so the
        #draw is never persisted server-side; same supplied pool as before.
        import secrets
        return json_response({'teamId':list(draw_clubs(CATALOG['starter_cup'],'native-group-0-v2:'+secrets.token_hex(16)))})
    if target==USER_LIST and headers.get(b'x-ut-sid')==SID.encode():
        #0103418c consumes a root object's tournamentId[] into active-ID vector.
        #An untouched local account has none. Never hide preserved progress.
        if (ACCOUNT/'tournaments.json').exists():return None
        from .native_tournament_state import load_all
        from .native_tournament_match import closed,ledger
        try:
            runs=load_all(ACCOUNT);journal=ledger(ACCOUNT)
            if runs and not START:return None
            active=[t for t,saved in sorted(runs.items()) if closed(ACCOUNT,saved,journal) is None]
        except (ValueError,TypeError,KeyError,OSError):return None
        return json_response({'tournamentId':active})
    for cup in CATALOG.values():
        if target==f'/fut/items/android/{cup.metadata_service_id}.json':return json_response(metadata(cup))
    return None


def save_request(method,target,headers,body,account):
    if (not START or ACCOUNT is None or account is None or Path(account).resolve()!=ACCOUNT or
            method!='PUT' or target not in {f'/ut/game/fifaworldmobile/tournament/user/{c.service_id}' for c in CATALOG.values()} or
            headers.get(b'host')!=b'10.0.2.2:18081' or headers.get(b'x-ut-sid')!=SID.encode() or
            headers.get(b'content-type')!=b'application/json' or
            headers.get(b'content-length')!=str(len(body)).encode()):
        raise ValueError('Not the captured isolated tournament save')
    if type(json.loads(body)) is not dict:raise ValueError('Invalid tournament save object')
    if SIM and json.loads(body).get('round')!=1:
        from .native_tournament_match import save_preview
        return save_preview(ACCOUNT,body,int(target.rsplit('/',1)[1]))
    from .native_tournament_state import preview
    return preview(ACCOUNT,body,int(target.rsplit('/',1)[1]))


def commit_request(method,target,headers,body,account):
    from .native_match_session import REPORT_PATH
    from .native_tournament_match import REWARDS
    if (
        target == REPORT_PATH and method == 'POST' and ACCOUNT is not None
        and account is not None and Path(account).resolve() == ACCOUNT
        and REWARDS is not None and REWARDS.get('version') == 'tournament_rewards_v2'
    ):
        from .tournament_match_report import response_for as report_reply
        return report_reply(method, target, headers, body, ACCOUNT, commit=True)
    if SIM and ACCOUNT is not None and account is not None and Path(account).resolve()==ACCOUNT and target in MATCH_PATHS:
        from .native_tournament_match import response_for as match_reply
        return match_reply(method,target,headers,body,account,commit=True)
    if START and method=='DELETE' and ACCOUNT is not None and account is not None and Path(account).resolve()==ACCOUNT and target in {f'/ut/game/fifaworldmobile/tournament/user/{c.service_id}' for c in CATALOG.values()}:
        from .native_tournament_match import commit_forfeit
        commit_forfeit(ACCOUNT,method,target,headers,body)
        return json_response({})
    if not START or method!='PUT' or target not in {f'/ut/game/fifaworldmobile/tournament/user/{c.service_id}' for c in CATALOG.values()}:return None
    save_request(method,target,headers,body,account)
    if type(json.loads(body)) is not dict:raise ValueError('Invalid tournament save object')
    if SIM and json.loads(body).get('round')!=1:
        from .native_tournament_match import commit_save
        commit_save(ACCOUNT,body,int(target.rsplit('/',1)[1]))
    else:
        from .native_tournament_state import commit
        commit(ACCOUNT,body,int(target.rsplit('/',1)[1]))
    return json_response({'result':'SUCCESS'})
