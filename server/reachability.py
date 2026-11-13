#!/usr/bin/env python3
"""Observed Nimble HTTP probes, device validation and local anonymous identity.

NetworkConnection requires HTTP 200; no response payload is consumed.
Evidence: JADX and captures runs 4–19. Identity transitions live in identity.py.
Only observed identity, auth, settings, reset, user info and empty inventory are served.
Successor requests remain unanswered; transport controls permit causal tests.
"""
import argparse
import datetime
import json
from pathlib import Path
import socket
import threading
from urllib.parse import urlsplit, parse_qs
if __package__:
    from . import identity, game_auth, http_framing, startup_control, startup, match_reset, user_info, purchased_items, victory_session
else:
    import identity
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from server import game_auth, http_framing, startup_control, startup, match_reset, user_info, purchased_items, victory_session

PROBE_HOSTS = {'cdn.skum.eamobile.com', 'www.ea.com'}
OK = b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'
from server.account_transaction import account_locked
from server.policy_memo import request_scoped

def status_of(response):
    """HTTP status recorded for a reply (None when unanswered)."""
    if not response:
        return None
    return int(response.split(b' ', 2)[1])


@account_locked
@request_scoped
def response_for(data,persona_id=None,fut_auth_code=False,victory_auth_code=False,game_session=False,settings=False,reset_candidate=None,user_info_candidate=None,purchased=False,victory=False,finalize=False,finalize_queue=False,credits=False,active_squad_candidate=None,owned_item_candidate=None,football_state=None,staff_bonuses=False,squad_list_candidate=False,football_catalog=None,football_card_display=False,offline_season_candidate=None,offline_current_candidate=None,offline_seasons_state=None,offline_seasons_definition=None,offline_create_match_candidate=None,accomplishments=False,save_squad=False,cycle_session=False,play_game=False,destroy_match=False,squad_mutations=False,goal_event=False,inventory_mutations=False,pack_catalog_empty_control=False,revival_pack_state=None,club_inventory=False,apply_card=False,offline_season_policy=None,native_simulation_discovery=False,native_simulation_create_ack=False,native_simulation_play_ack=False,native_simulation_end_ack=False,native_season_completion=False,native_match_reward_policy=None,market_empty_control=False,native_match_pack_policy=None,native_match_session=False,native_match_xp=False,native_report_end_identity=False,native_season_coins=False,native_atomic_matches=False,native_played_matches=False,native_mixed_matches=False,native_played_report_end_identity=False,native_distinct_season_ids=False,native_atomic_season_rewards=False,native_early_season_completion=False,native_difficulty_rewards=False,native_season_prize_display=False,*,_completion_context=None):
    if _completion_context is not None:_completion_context.clear()
    if is_probe(data):
        return OK
    try:
        lines=data.split(b'\r\n'); method,target,version=lines[0].decode('ascii').split()
        headers={line.split(b':',1)[0].lower():line.split(b':',1)[1].strip()
                 for line in lines[1:] if b':' in line}
        from server.native_pack_sessions import normalize
        headers=normalize(headers)
        from server.native_pack_sessions import is_stale,stale_reply
        if is_stale(headers):
            from server.local_packs import PackStore
            from server.local_football import FootballStore
            from server.local_content import ContentCatalog
            parts=http_framing.split_head(data)
            if parts is None:return None
            return stale_reply(method,target,headers,parts[1],PackStore(revival_pack_state),FootballStore(football_state,ContentCatalog(football_catalog)))
        url=urlsplit(target); query=parse_qs(url.query)
        parts=http_framing.split_head(data)
        body=parts[1] if parts else b''
        from server.first_run_account import pending_session
        setup_pending = football_state is not None and pending_session(Path(football_state).parent) is not None
        if target in (
            '/UX.cmconfig', '/FUTPackImages/packs_backgrounds_5000011.png.cmmetadata',
            '/FUTPackImages/packs_backgrounds_5000011.png',
        ):
            from server.store_single_artwork import content_response_for
            content_reply = content_response_for(
                method, target, headers, body,
                Path(football_state).parent if football_state else None,
            )
            if content_reply is not None:
                return content_reply
        from server import welcome_gift
        gift_image=welcome_gift.image_response(method,target,headers,body)
        if gift_image is not None:return gift_image
        from server import native_tournament_catalog
        tournament_read=native_tournament_catalog.response_for(method,target,headers,body,
            Path(football_state).parent if football_state else None)
        if tournament_read is not None:return tournament_read
        from server import market_protocol
        market_read=market_protocol.response_for(method,target,headers,body,
            Path(football_state).parent if football_state else None)
        if market_read is not None:return market_read
        from server import native_player_exchange_protocol
        native_player_exchange_protocol.recover(Path(football_state).parent if football_state else None)
        exchange_read=native_player_exchange_protocol.response_for(method,target,headers,body,
            Path(football_state).parent if football_state else None)
        if exchange_read is not None:return exchange_read
        from server import season_choice_preview
        preview=season_choice_preview.response_for(method,target,headers,body,
            Path(offline_seasons_state).parent if offline_seasons_state else None)
        if preview is not None:return preview
        from server import native_free_coins_protocol
        from server import native_quick_sell_protocol
        native_quick_sell_protocol.recover(football_state)
        from server import native_free_packs_protocol
        native_free_packs_protocol.recover(football_state)
        native_free_coins_protocol.recover(football_state)
        if revival_pack_state and not setup_pending:
            from server.local_packs import PackStore
            from server.local_football import FootballStore
            from server.local_content import ContentCatalog
            from server.pack_protocol import recover_transactions
            # A failed prior handler may leave an authorized durable intent.
            # Complete it before credits reads or another match/reward proposal.
            recover_transactions(PackStore(revival_pack_state),FootballStore(football_state,ContentCatalog(football_catalog)) if football_state else None)
        if native_season_completion:
            from server.native_season_completion import NativeSeasonCoordinator
            coordinator=NativeSeasonCoordinator(Path(offline_seasons_state).parent,enabled=True,reward_policy=native_match_reward_policy,match_pack_policy=native_match_pack_policy,native_match_xp=native_match_xp,backend_report_bound_end_identity=native_report_end_identity,backend_season_coin_rewards=native_season_coins,backend_season_awards_projection=native_season_coins,native_atomic_matches=native_atomic_matches,native_played_matches=native_played_matches,native_mixed_matches=native_mixed_matches,backend_played_report_bound_end_identity=native_played_report_end_identity,backend_distinct_season_ids=native_distinct_season_ids,backend_atomic_season_rewards=native_atomic_season_rewards,native_early_season_completion=native_early_season_completion,backend_difficulty_rewards=native_difficulty_rewards,backend_season_prize_display=native_season_prize_display)
            recovered=coordinator.recover()
            season_choice_preview.guard_match(Path(offline_seasons_state).parent,method,target)
            choice_read=season_choice_preview.response_for(method,target,headers,body,
                Path(offline_seasons_state).parent,after_recovery=True)
            if choice_read is not None:return choice_read
            if _completion_context is not None:
                # Recovery/validation above remains mandatory. A settled pure
                # read cannot commit a match or initialize a season afterwards.
                # GET deletion/selection routes do mutate and retain follow-up.
                _completion_context['settled_read']=(
                    method=='GET' and not body and recovered['active_match'] is None
                    and recovered['prepared'] is None and recovered['cycle']['status']=='active'
                    and not target.startswith(('/ut/delete/','/ut/game/fifaworldmobile/squad/')))
            if native_atomic_matches:
                from server.native_atomic_match import read_response
                if method=='PUT' and target.startswith('/ut/game/fifaworldmobile/season/'):
                    proposal=coordinator.preview(method,target,headers,body)
                    return identity.json_response(proposal['response']) if proposal else None
                atomic_read=read_response(coordinator,recovered,method,target,headers,body)
                if atomic_read is not None:return atomic_read
            if native_match_session:
                from server.native_match_session import response_for as session_response,report_response_for
                candidate=session_response(method,target,headers,body,coordinator)
                if candidate is not None:return candidate
                from server.native_match_session import REPORT_PATH
                if target==REPORT_PATH and native_match_xp:
                    proposal=coordinator.preview(method,target,headers,body)
                    return victory_session.xml_response(proposal['response_xml']) if proposal else None
                candidate=report_response_for(method,target,headers,body,coordinator)
                if candidate is not None:return candidate
            routes=('/ut/game/fifaworldmobile/match','/ut/game/fifaworldmobile/match/end') if native_played_matches else ('/ut/game/fifaworldmobile/match/sim','/ut/game/fifaworldmobile/match/sim/end')
            if native_mixed_matches:routes=('/ut/game/fifaworldmobile/match','/ut/game/fifaworldmobile/match/end','/ut/game/fifaworldmobile/match/sim','/ut/game/fifaworldmobile/match/sim/end')
            if native_played_matches and target in ('/ut/game/fifaworldmobile/match/sim','/ut/game/fifaworldmobile/match/sim/end'):return None
            if target in routes:
                proposal=coordinator.preview(method,target,headers,body)
                return identity.json_response(proposal['response']) if proposal else None
        if revival_pack_state and (not setup_pending or method == 'GET'):
            from server.local_packs import PackStore
            from server.pack_protocol import response_for as pack_response
            from server.local_football import FootballStore
            from server.local_content import ContentCatalog
            reply=pack_response(method,target,headers,body,PackStore(revival_pack_state),FootballStore(football_state,ContentCatalog(football_catalog)) if football_state else None)
            if reply:return reply
        if market_empty_control:
            from server.market_search_control import response_for as market_control_response
            reply=market_control_response(method,target,headers,body)
            if reply:return reply
        if pack_catalog_empty_control:
            from server.pack_catalog_control import response_for as pack_control_response
            reply=pack_control_response(method,target,headers,body)
            if reply:return reply
        identity_response=identity.response_for(method,target,headers,body,persona_id,fut_auth_code,victory_auth_code)
        if identity_response:return identity_response
        if game_session:
            game_response=game_auth.response_for(method,target,headers,body)
            if game_response:return game_response
        if settings:
            # Settings are cached by the original client before CreateUser.
            # Preload the already supported Sim UI setting for managed setup;
            # this does not admit any match/reward endpoint before creation.
            startup_response=startup.response_for(
                method, target, headers, body,
                native_simulation_discovery or setup_pending,
            )
            if startup_response:return startup_response
        if native_simulation_create_ack and football_state and offline_seasons_state:
            from server.native_simulation_protocol import create_ack
            from server.local_football import FootballStore
            from server.local_content import ContentCatalog
            from server.local_seasons import SeasonStore,load_definition
            reply=create_ack(method,target,headers,body,SeasonStore(offline_seasons_state,load_definition(offline_seasons_definition)),FootballStore(football_state,ContentCatalog(football_catalog)),enabled=True)
            if reply:return reply
        if native_simulation_play_ack and football_state:
            from server.native_simulation_protocol import play_ack
            from server.local_football import FootballStore
            from server.local_content import ContentCatalog
            reply=play_ack(method,target,headers,body,FootballStore(football_state,ContentCatalog(football_catalog)),enabled=True)
            if reply:return reply
        if native_simulation_end_ack and football_state and offline_seasons_state:
            from server.native_simulation_protocol import end_ack
            from server.local_football import FootballStore
            from server.local_content import ContentCatalog
            from server.local_seasons import SeasonStore,load_definition
            reply=end_ack(method,target,headers,body,SeasonStore(offline_seasons_state,load_definition(offline_seasons_definition)),FootballStore(football_state,ContentCatalog(football_catalog)),enabled=True)
            if reply:return reply
        from server import first_run as first_run_preview, local_profile as first_run_profile
        fav_team = first_run_preview.preview(method, target, headers, body,
                                                       first_run_profile.PROFILE_PATH)
        if fav_team:
            return fav_team
        if reset_candidate:
            # FIRST-001: a selected account without a club takes the stock
            # new-user branch (HTTP465 -> LS_CONNECTED_NEW_USER).
            from server import first_run, local_profile
            new_user = first_run.reset_response(method, target, headers, body, local_profile.PROFILE_PATH)
            if new_user:
                return new_user
            reset_response=match_reset.response_for(method,target,headers,body,reset_candidate)
            if reset_response:return reset_response
        if football_state:
            from server import market_protocol
            hub=market_protocol.hub_response(method,target,headers,body,Path(football_state).parent)
            if hub:return hub
        if user_info_candidate:
            user_store=None
            if football_state and target=='/ut/game/fifaworldmobile/user':
                from server.local_football import FootballStore
                from server.local_content import ContentCatalog
                user_store=FootballStore(football_state,ContentCatalog(football_catalog))
            user_response=user_info.response_for(method,target,headers,body,user_info_candidate,persona_id,user_store,preserve_coins=native_simulation_end_ack)
            if user_response:return user_response
        if staff_bonuses:
            from server import staff_bonuses as staff_adapter
            reply=staff_adapter.response_for(method,target,headers,body)
            if reply:return reply
        if squad_list_candidate:
            from server import squad_list as list_adapter
            list_store=None
            if football_state:
                from server.local_football import FootballStore
                from server.local_content import ContentCatalog
                list_store=FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None)
            reply=list_adapter.response_for(method,target,headers,body,list_store)
            if reply:return reply
        season_store=None
        if offline_seasons_state and offline_seasons_definition:
            from server import offline_seasons_protocol
            from server.local_seasons import SeasonStore,load_definition
            season_store=SeasonStore(offline_seasons_state,load_definition(offline_seasons_definition))
            from server.season_revival_policy import load_policy
            policy=load_policy(offline_season_policy) if offline_season_policy else None
            reply=offline_seasons_protocol.response_for(method,target,headers,body,season_store,policy)
            if reply:return reply
        if offline_create_match_candidate:
            from server import offline_create_match
            from server.local_football import FootballStore
            from server.local_content import ContentCatalog
            create_football=FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None) if football_state else None
            reply=offline_create_match.response_for(method,target,headers,body,offline_create_match_candidate,season_store,create_football)
            if reply:return reply
        if offline_season_candidate:
            from server import offline_season_list
            reply=offline_season_list.response_for(method,target,headers,body,offline_season_candidate)
            if reply:return reply
        if offline_current_candidate:
            from server import offline_current_season
            reply=offline_current_season.response_for(method,target,headers,body,offline_current_candidate)
            if reply:return reply
        if football_state:
            if apply_card:
                reply=native_free_packs_protocol.response_for(method,target,headers,body,football_state)
                if reply:return reply
                reply=native_free_coins_protocol.response_for(method,target,headers,body,football_state)
                if reply:return reply
                from server.apply_card import response_for as apply_response
                from server.local_football import FootballStore
                from server.local_content import ContentCatalog
                reply=apply_response(method,target,headers,body,FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None))
                if reply:return reply
            if inventory_mutations:
                from server.club_item_actions import response_for as club_activation_response
                from server.local_football import FootballStore
                from server.local_content import ContentCatalog
                reply=club_activation_response(method,target,headers,body,FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None))
                if reply:return reply
                from server import inventory_protocol
                from server.local_football import FootballStore
                from server.local_content import ContentCatalog
                reply=inventory_protocol.response_for(method,target,headers,body,FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None))
                if reply:return reply
            if club_inventory:
                from server.club_inventory import response_for as club_response
                from server.native_club_statistics import response_for as statistics_response
                from server.local_football import FootballStore
                from server.local_content import ContentCatalog
                club_store=FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None)
                reply=statistics_response(method,target,headers,body,club_store)
                if reply:return reply
                reply=club_response(method,target,headers,body,club_store)
                if reply:return reply
            from server import football_protocol
            from server.local_football import FootballStore
            from server.local_content import ContentCatalog
            if destroy_match:
                from server import destroy_match as destroy_adapter
                reply=destroy_adapter.response_for(method,target,headers,body,FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None))
                if reply:return reply
            if play_game:
                from server import play_game as play_adapter
                reply=play_adapter.response_for(method,target,headers,body,FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None))
                if reply:return reply
            if save_squad:
                from server import save_squad as save_adapter
                reply=save_adapter.response_for(method,target,headers,body,FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None),squad_mutations)
                if reply:return reply
            reply=football_protocol.response_for(method,target,headers,body,FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None),squad_by_id=squad_list_candidate,card_display=football_card_display)
            if reply:return reply
        if owned_item_candidate:
            from server import owned_item_candidate as owned_adapter
            reply=owned_adapter.response_for(method,target,headers,body,owned_item_candidate)
            if reply:return reply
        if purchased:
            purchased_response=purchased_items.response_for(method,target,headers,body)
            if purchased_response:return purchased_response
        if victory:
            victory_response=victory_session.response_for(method,target,headers,body,persona_id)
            if victory_response:return victory_response
        if active_squad_candidate:
            from server import active_squad
            candidate=active_squad.response_for(method,target,headers,body,active_squad_candidate)
            if candidate:return candidate
        if credits:
            from server import user_credits
            candidate=user_credits.response_for(method,target,headers,body)
            if candidate:return candidate
        if cycle_session:
            from server import cycle_session as cycle_adapter
            candidate=cycle_adapter.response_for(method,target,headers,body)
            if candidate:return candidate
        if goal_event:
            from server import goal_event as goal_adapter
            report_session=None
            if native_match_session and target==goal_adapter.PATH:
                from server.native_match_session import active_session_id
                report_session=active_session_id(coordinator)
            candidate=goal_adapter.response_for(method,target,headers,body,match_session_id=report_session)
            if candidate:return candidate
        if accomplishments:
            from server import persona_accomplishments
            candidate=persona_accomplishments.response_for(method,target,headers,body)
            if candidate:return candidate
        if finalize_queue:
            from server import finalize_authentication
            candidate=finalize_authentication.queue_response_for(method,target,headers,body)
            if candidate:return candidate
        if finalize:
            from server import finalize_authentication
            candidate=finalize_authentication.response_for(method,target,headers,body)
            if candidate:return candidate
        if (method=='GET' and headers.get(b'host')==b'10.0.2.2:18081'
            and url.path=='/user/api/android/validateDeviceID'
            and query.get('apiVer')==['1.0.0'] and query.get('hwId')==['2363']
            and len(query.get('eadeviceid',[]))==1):
            # Run 13 supplies its cached ID; the callback consumes only deviceId.
            body=json.dumps({'deviceId':query['eadeviceid'][0]},separators=(',',':')).encode()
            return b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body
    except (ValueError,UnicodeError):
        pass
    return None

def is_probe(data):
    lines = data.split(b'\r\n')
    if not lines or lines[0] != b'GET / HTTP/1.1':
        return False
    headers = {}
    for line in lines[1:]:
        if b':' in line:
            key, value = line.split(b':', 1)
            headers[key.lower()] = value.strip().decode('ascii', errors='replace')
    return headers.get(b'host', '').lower() in PROBE_HOSTS

def handle(conn, peer, output, persona_id=None,fut_auth_code=False,victory_auth_code=False,game_session=False,control=None,settings=False,reset_candidate=None,user_info_candidate=None,purchased=False,victory=False,finalize=False,finalize_queue=False,credits=False,active_squad_candidate=None,owned_item_candidate=None,football_state=None,staff_bonuses=False,squad_list_candidate=False,football_catalog=None,football_card_display=False,offline_season_candidate=None,offline_current_candidate=None,offline_seasons_state=None,offline_seasons_definition=None,offline_create_match_candidate=None,accomplishments=False,save_squad=False,cycle_session=False,play_game=False,destroy_match=False,squad_mutations=False,goal_event=False,inventory_mutations=False,pack_catalog_empty_control=False,revival_pack_state=None,club_inventory=False,apply_card=False,offline_season_policy=None,native_simulation_discovery=False,native_simulation_create_ack=False,native_simulation_play_ack=False,native_simulation_end_ack=False,native_season_completion=False,native_match_reward_policy=None,market_empty_control=False,native_match_pack_policy=None,native_match_session=False,native_match_xp=False,native_report_end_identity=False,native_season_coins=False,native_atomic_matches=False,native_played_matches=False,native_mixed_matches=False,native_played_report_end_identity=False,native_distinct_season_ids=False,native_atomic_season_rewards=False,native_early_season_completion=False,native_difficulty_rewards=False,native_season_prize_display=False, *, local_transport=False):
    with conn:
        conn.settimeout(5)
        data = b''
        accepted_utc=datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            data=http_framing.read_request(conn)
        except (TimeoutError, ValueError):
            return
        wire_data = data
        bootstrap = None
        if local_transport:
            from server.loopback_transport import canonical_request, bootstrap_response
            data = canonical_request(data)
            bootstrap = bootstrap_response(data)
        if bootstrap is not None:
            with output.open('a') as stream:
                stream.write(json.dumps({
                    'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    'action': 'loopback_bootstrap', 'request': wire_data.decode('latin1'),
                    'response_status': status_of(bootstrap),
                    'response': bootstrap.decode('latin1'),
                }) + '\n')
            conn.sendall(bootstrap)
            return
        completion_context = {}
        response = response_for(bytes(data),persona_id,fut_auth_code,victory_auth_code,game_session,settings,reset_candidate,user_info_candidate,purchased,victory,finalize,finalize_queue,credits,active_squad_candidate,owned_item_candidate,football_state,staff_bonuses,squad_list_candidate,football_catalog,football_card_display,offline_season_candidate,offline_current_candidate,offline_seasons_state,offline_seasons_definition,offline_create_match_candidate,accomplishments,save_squad,cycle_session,play_game,destroy_match,squad_mutations,goal_event,inventory_mutations,pack_catalog_empty_control,revival_pack_state,club_inventory,apply_card,offline_season_policy,native_simulation_discovery,native_simulation_create_ack,native_simulation_play_ack,native_simulation_end_ack,native_season_completion,native_match_reward_policy,market_empty_control,native_match_pack_policy,native_match_session,native_match_xp,native_report_end_identity,native_season_coins,native_atomic_matches,native_played_matches,native_mixed_matches,native_played_report_end_identity,native_distinct_season_ids,native_atomic_season_rewards,native_early_season_completion,native_difficulty_rewards,native_season_prize_display,_completion_context=completion_context)
        name=startup_control.dependency(data)
        request_key=data.split(b'\r\n',1)[0].decode('ascii').rsplit(' ',1)[0]
        action=startup_control.action(control,name,request_key,data,football_state,football_catalog)
        # This opt-in mapped adapter may pass the default unknown-successor
        # hold only after validation produced a response. Exact experimental
        # holds/closes retain priority; unsupported requests remain unchanged.
        from server.apply_card import is_source_path as apply_source_path
        if (apply_card and response is not None and name=='successor' and
            request_key.startswith('POST ') and apply_source_path(request_key[5:]) and
            control is not None and request_key not in json.loads(control.read_text()).get('requests',{})):
            action='pass'
        if (inventory_mutations and response is not None and name=='successor' and
            data.startswith(b'PUT /ut/game/fifaworldmobile/item/') and
            control is not None and request_key not in json.loads(control.read_text()).get('requests',{})):
            action='pass'
        # The original Division9 list397 and initial save398 certify the
        # same adapter on the configured next division. Explicit experiment
        # holds/closes still win; unrelated unknown endpoints remain held.
        if (native_season_completion and response is not None and name=='successor' and control is not None
            and request_key not in json.loads(control.read_text()).get('requests',{})):
            head,body,_=http_framing.split_head(data)
            method,target,_=head.splitlines()[0].decode('ascii').split()
            from server.season_forfeit import selected as forfeit_selected,reset_path
            if ((method=='GET' and target.startswith('/ut/game/fifaworldmobile/season/list?')) or
                (method=='PUT' and target.startswith('/ut/game/fifaworldmobile/season/') and target.endswith('/user')) or
                (method=='PUT' and forfeit_selected(Path(offline_seasons_state).parent) and reset_path(target) is not None)):
                action='pass'
        if action != 'pass':response=None
        record = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'accepted_utc': accepted_utc,
                  'dependency': name, 'action': action,
                  'peer': peer, 'request': wire_data.decode('latin1'),
                  'response_status': status_of(response),
                  'response': response.decode('latin1') if response else None}
        with output.open('a') as stream:
            stream.write(json.dumps(record) + '\n')
        if action=='hold':
            released=startup_control.wait_release(control,name,request=request_key,data=data,football_state=football_state,football_catalog=football_catalog)
            if released=='pass':
                response=response_for(data,persona_id,fut_auth_code,victory_auth_code,game_session,settings,reset_candidate,user_info_candidate,purchased,victory,finalize,finalize_queue,credits,active_squad_candidate,owned_item_candidate,football_state,staff_bonuses,squad_list_candidate,football_catalog,football_card_display,offline_season_candidate,offline_current_candidate,offline_seasons_state,offline_seasons_definition,offline_create_match_candidate,accomplishments,save_squad,cycle_session,play_game,destroy_match,squad_mutations,goal_event,inventory_mutations,pack_catalog_empty_control,revival_pack_state,club_inventory,apply_card,offline_season_policy,native_simulation_discovery,native_simulation_create_ack,native_simulation_play_ack,native_simulation_end_ack,native_season_completion,native_match_reward_policy,market_empty_control,native_match_pack_policy,native_match_session,native_match_xp,native_report_end_identity,native_season_coins,native_atomic_matches,native_played_matches,native_mixed_matches,native_played_report_end_identity,native_distinct_season_ids,native_atomic_season_rewards,native_early_season_completion,native_difficulty_rewards,native_season_prize_display,_completion_context=completion_context)
            record.update(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                          action='released_'+released,
                          response_status=status_of(response),
                          response=response.decode('latin1') if response else None)
            with output.open('a') as stream:stream.write(json.dumps(record)+'\n')
        if response:
            from server.account_transaction import ACCOUNT_LOCK
            with ACCOUNT_LOCK:
                # Parse once for the commit adapters; unchanged reads have no
                # second match/initialization phase after their recovered preview.
                head,body,_=http_framing.split_head(data)
                method,target,_=head.splitlines()[0].decode('ascii').split()
                headers={line.split(b':',1)[0].lower():line.split(b':',1)[1].strip() for line in head.splitlines()[1:] if b':' in line}
                from server.native_pack_sessions import normalize
                headers=normalize(headers)
                from server.native_pack_sessions import is_stale,commit_auth,stale_reply
                if is_stale(headers):
                    from server.local_packs import PackStore
                    from server.local_football import FootballStore
                    from server.local_content import ContentCatalog
                    response=stale_reply(method,target,headers,body,PackStore(revival_pack_state),FootballStore(football_state,ContentCatalog(football_catalog)))
                    conn.sendall(response);return
                commit_auth(method,target,headers,body)
                from server.favorites import commit_request as commit_favorites
                favorites_commit = commit_favorites(method, target, headers, body)
                if favorites_commit is not None:
                    with output.open('a') as stream:
                        stream.write(json.dumps({
                            'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            'action': 'favorites_committed', 'request': wire_data.decode('latin1'),
                            'response': favorites_commit.decode('latin1'),
                        }) + '\n')
                    conn.sendall(favorites_commit)
                    return
                from server import first_run, local_profile
                first_run_commit = first_run.commit_request(method, target, headers, body,
                                                             local_profile.PROFILE_PATH)
                if first_run_commit is not None:
                    record = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                              'action': 'first_run_committed', 'request': wire_data.decode('latin1'),
                              'response': first_run_commit.decode('latin1')}
                    with output.open('a') as stream:
                        stream.write(json.dumps(record) + '\n')
                    conn.sendall(first_run_commit)
                    return
                from server import native_tournament_catalog
                tournament_commit=native_tournament_catalog.commit_request(method,target,headers,body,
                    Path(football_state).parent if football_state else None)
                if tournament_commit is not None:
                    response=tournament_commit
                    with output.open('a') as stream:stream.write(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'action':'tournament_initial_committed','request':wire_data.decode('latin1'),'response':response.decode('latin1')})+'\n')
                    #Exclusive owner: never pass a tournament commit into Seasons.
                    conn.sendall(response);return
                from server import market_protocol
                market_commit=market_protocol.commit_request(method,target,headers,body,
                    Path(football_state).parent if football_state else None)
                if market_commit is not None:
                    with output.open('a') as stream:stream.write(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'action':'market_committed','request':wire_data.decode('latin1'),'response':market_commit.decode('latin1')})+'\n')
                    conn.sendall(market_commit);return
                from server import native_player_exchange_protocol
                committed_exchange=native_player_exchange_protocol.commit_request(method,target,headers,body,
                    Path(football_state).parent if football_state else None)
                if committed_exchange is not None:
                    response=committed_exchange
                    with output.open('a') as stream:stream.write(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'action':'player_exchange_committed','request':wire_data.decode('latin1'),'response':response.decode('latin1')})+'\n')
                completion_followup=native_season_completion and not completion_context.get('settled_read',False)
                from server import season_choice_preview
                atomic_save_handled=season_choice_preview.commit_request(method,target,headers,body,
                    Path(offline_seasons_state).parent if offline_seasons_state else None)
                if completion_followup:
                    from server.native_season_completion import NativeSeasonCoordinator
                    from server.account_transaction import ACCOUNT_LOCK
                    with ACCOUNT_LOCK:
                        coordinator=NativeSeasonCoordinator(Path(offline_seasons_state).parent,enabled=True,reward_policy=native_match_reward_policy,match_pack_policy=native_match_pack_policy,native_match_xp=native_match_xp,backend_report_bound_end_identity=native_report_end_identity,backend_season_coin_rewards=native_season_coins,backend_season_awards_projection=native_season_coins,native_atomic_matches=native_atomic_matches,native_played_matches=native_played_matches,native_mixed_matches=native_mixed_matches,backend_played_report_bound_end_identity=native_played_report_end_identity,backend_distinct_season_ids=native_distinct_season_ids,backend_atomic_season_rewards=native_atomic_season_rewards,native_early_season_completion=native_early_season_completion,backend_difficulty_rewards=native_difficulty_rewards,backend_season_prize_display=native_season_prize_display)
                        committed=coordinator.accept(method,target,headers,body)
                        if committed is not None:
                            from server.item_history import reconcile_seasons
                            reconcile_seasons(Path(offline_seasons_state).parent)
                            atomic_save_handled=committed['operation'] in ('atomic_save','atomic_save_retry','atomic_initialization','atomic_initialization_retry','season_forfeit','season_forfeit_retry','match_forfeit_save')
                            if not committed.get('preserve_response'):
                                response=(victory_session.xml_response(committed['response_xml']) if 'response_xml' in committed else identity.json_response(committed['response']))
                            with output.open('a') as stream:stream.write(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'action':'native_season_lifecycle_committed','request':wire_data.decode('latin1'),'response':response.decode('latin1'),'operation':committed['operation']})+'\n')
                if apply_card and football_state:
                    from server import apply_card as apply_adapter
                    from server.local_football import FootballStore
                    from server.local_content import ContentCatalog
                    if method=='POST' and apply_adapter.is_source_path(target):
                        from server import native_free_coins_protocol
                        from server import native_free_packs_protocol
                        response=native_free_packs_protocol.commit_request(method,target,headers,body,football_state)
                        if response is None:
                            response=native_free_coins_protocol.commit_request(method,target,headers,body,football_state)
                        if response is None:
                            response=apply_adapter.commit_request(method,target,headers,body,FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None))
                        with output.open('a') as stream:stream.write(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'action':'apply_card_committed','request':wire_data.decode('latin1'),'response':response.decode('latin1')})+'\n')
                if revival_pack_state and football_state and method=='POST' and target=='/ut/game/fifaworldmobile/purchased/items':
                    from server.pack_protocol import commit_request as commit_pack
                    from server.local_packs import PackStore
                    from server.local_football import FootballStore
                    from server.local_content import ContentCatalog
                    committed=commit_pack(method,target,headers,body,PackStore(revival_pack_state),FootballStore(football_state,ContentCatalog(football_catalog)))
                    if committed is not None:
                        response=committed
                        with output.open("a") as stream:stream.write(json.dumps({"utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"action":"pack_committed","request":wire_data.decode("latin1"),"response":response.decode("latin1")})+"\n")
                if inventory_mutations and football_state:
                    from server.club_item_actions import commit_request as commit_club_activation
                    from server.local_football import FootballStore
                    from server.local_content import ContentCatalog
                    activated=commit_club_activation(method,target,headers,body,FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None))
                    if activated is not None:
                        response=activated
                        with output.open('a') as stream:stream.write(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'action':'club_rename_committed' if target=='/ut/game/fifaworldmobile/user/club' else 'club_item_activation_committed','request':wire_data.decode('latin1'),'response':response.decode('latin1')})+'\n')
                    from server.inventory_protocol import commit_request as commit_inventory
                    from server.local_football import FootballStore
                    from server.local_content import ContentCatalog
                    committed_inventory=commit_inventory(method,target,headers,body,FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None))
                    if isinstance(committed_inventory,bytes):
                        response=committed_inventory
                        with output.open('a') as stream:stream.write(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'action':'quick_sell_committed','request':wire_data.decode('latin1'),'response':response.decode('latin1')})+'\n')
                if squad_mutations and save_squad and football_state:
                    from server.save_squad import commit_request as commit_squad
                    from server.local_football import FootballStore
                    from server.local_content import ContentCatalog
                    if ((method in ('POST','PUT','DELETE') and
                        (target=='/ut/game/fifaworldmobile/squad' or target.startswith('/ut/game/fifaworldmobile/squad/'))) or
                        (method=='GET' and target.startswith('/ut/delete/game/fifaworldmobile/squad/'))):
                        squad_store=FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None)
                        from server.squad_lineup_history import snapshot as lineup_snapshot
                        lineup_before=lineup_snapshot(squad_store.load(1))
                        committed_squad=commit_squad(method,target,headers,body,squad_store,True)
                        # 1577: remember a replaced lineup for a same-session stale
                        # PlaySim. Both squad commit paths reach here; no-ops record nothing.
                        from server.squad_lineup_history import record as record_lineup
                        record_lineup(
                            Path(football_state).parent, headers,
                            lineup_before, lineup_snapshot(squad_store.load(1)),
                        )
                        if isinstance(committed_squad,bytes):
                            response=committed_squad
                            with output.open('a') as stream:stream.write(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'action':'squad_committed','request':wire_data.decode('latin1'),'response':response.decode('latin1')})+'\n')
                    elif method=='GET':
                        from server.squad_management import commit_loaded_squad
                        activation=commit_loaded_squad(method,target,headers,body,FootballStore(football_state,ContentCatalog(football_catalog) if football_catalog else None))
                        if activation is not None:
                            with output.open('a') as stream:stream.write(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'action':'squad_loaded_selection_committed','request':wire_data.decode('latin1'),'selection':activation})+'\n')
                if offline_seasons_state and offline_seasons_definition and not atomic_save_handled:
                    if method=='PUT':
                        from server.local_seasons import SeasonStore,load_definition
                        from server.offline_seasons_protocol import commit_request
                        commit_request(method,target,headers,body,SeasonStore(offline_seasons_state,load_definition(offline_seasons_definition)))
                    if completion_followup:coordinator.observe_initialization()
                if completion_followup:
                    from server.native_reward_ack_lab import claim_drop
                    dropped=claim_drop(control,Path(offline_seasons_state).parent,data,response,coordinator)
                    if dropped is not None:
                        dropped.update(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                       request=wire_data.decode('latin1'),response_delivered=False)
                        with output.open('a') as stream:stream.write(json.dumps(dropped)+'\n')
                        return
                conn.sendall(response)

def configure_runtime(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18081)
    parser.add_argument('--persona-id',type=int,default=None,
                        help='Controlled native persona-ID gate experiment; absent means empty list')
    parser.add_argument('--fut-auth-code',action='store_true',
                        help='Answer only the FUT-SERVER auth-code GET observed in run24')
    parser.add_argument('--victory-auth-code',action='store_true',
                        help='Answer the captured parallel Victory code request to measure config startup')
    parser.add_argument('--game-session',action='store_true',
                        help='Answer only run28 POST /ut/auth with a local SID')
    parser.add_argument('--startup-control',type=Path,
                        help='Reversible hold/close intervention for local authenticated startup requests')
    parser.add_argument('--settings',action='store_true',
                        help='Answer only captured authenticated startup settings GET with {}')
    reset_group=parser.add_mutually_exclusive_group()
    reset_group.add_argument('--match-reset',dest='match_reset_candidate',
                        action='store_const',const='object',
                        help='Answer captured ResetMatch with run34 verified HTTP200 {}')
    reset_group.add_argument('--match-reset-candidate',choices=['empty','object'],
                        help='Scoped ResetMatch response experiment; successor stays unanswered')
    user_group=parser.add_mutually_exclusive_group()
    user_group.add_argument('--user-info',dest='user_info_candidate',action='store_const',const='persona',
                        help='Answer GetUserInfo with only the existing local persona ID (run36)')
    user_group.add_argument('--user-info-candidate',choices=['empty-object','persona'],
                        help='Scoped GetUserInfo experiment; all successor requests remain unanswered')
    parser.add_argument('--purchased-items',action='store_true',
                        help='Answer captured PurchasedItems with run38 verified HTTP200 {}; no item records')
    parser.add_argument('--persona-accomplishments',action='store_true',help='Opt-in captured native empty accomplishment progression collection; no rewards/state')
    parser.add_argument('--cycle-session',action='store_true',help='Opt-in exact CycleSession; return existing token only, no account mutation')
    parser.add_argument('--destroy-match',action='store_true',help='Opt-in exact authenticated match/end zero-reward completion; no domain mutation')
    parser.add_argument('--play-game',action='store_true',help='Opt-in observed starting-eleven transport ACK; no match/domain mutation')
    parser.add_argument('--squad-mutations',action='store_true',help='Opt-in captured existing-squad player/formation edits; atomic account-specific persistence')
    parser.add_argument('--save-squad',action='store_true',help='Opt-in exact existing squad0 captain/kick-taker acknowledgement; no domain mutation')
    parser.add_argument('--victory-session',action='store_true',
                        help='Experimental native initialization XML candidates; hub/frontend readiness remains unverified')
    parser.add_argument('--finalize-authentication',action='store_true',
                        help='Opt-in namespace-only response for captured FOS PUT; no profile fields')
    parser.add_argument("--finalize-queue-prerequisites",action="store_true",
                        help="Opt-in empty XML for run99/100 proven native transport gates")
    parser.add_argument("--user-credits",action="store_true",help="Opt-in captured GetUserCredits backed by persistent local profile")
    parser.add_argument('--squad-navigation','--squad-list-candidate',dest='squad_list_candidate',action='store_true',help='Verified existing-ID0 list and by-ID load for normal TeamManagement')
    parser.add_argument('--squad-management',action='store_true',help='Explicit named squad creation/bank candidate; no default activation')
    parser.add_argument('--staff-bonuses',action='store_true',help='Neutral Squad-triggered staff-bonus response only')
    parser.add_argument('--offline-season-policy',type=Path,help='Opt-in revival thresholds only; no awards or division commit')
    parser.add_argument('--offline-season-choices-preview',action='store_true',help='Isolated read-only native competition names/requirements experiment; no saves or rewards, default off')
    parser.add_argument('--offline-season-choices-start',action='store_true',help='Isolated native initial competition selection through existing journal; no matches or rewards, default off')
    parser.add_argument('--offline-season-choices-handoff',action='store_true',help='Isolated completed-cycle next-competition selection only; no new gameplay/rewards, default off')
    parser.add_argument('--offline-season-choices-gameplay',action='store_true',help='Isolated first-fixture test of a genuinely selected competition; default off, no rollover')
    parser.add_argument('--offline-season-choices-cycle',action='store_true',help='Isolated selected-competition season test; genuine results only, default off')
    parser.add_argument('--season-choice-release',action='store_true',help='Certificate-backed prospective normal competition/difficulty admission')
    parser.add_argument('--native-season-forfeit',action='store_true',help='Original season forfeiture on an archived candidate or certificate-admitted normal account')
    parser.add_argument('--native-match-forfeit',action='store_true',help='Source-bound original QUIT/loss persistence; isolated or certified admission, default off')
    parser.add_argument('--native-pack-sessions',action='store_true',help='Archived isolated pack-session contract candidate; default off')
    parser.add_argument('--offline-season-candidate',type=Path,help='Opt-in exact offline SeasonList candidate; no other competition response')
    parser.add_argument('--offline-seasons-state',type=Path,help='Local current-season store; only captured fresh save implemented')
    parser.add_argument('--offline-seasons-definition',type=Path,help='Separate locally authored offline rules/fixture identifiers')
    parser.add_argument('--offline-current-candidate',type=Path,help='Opt-in exact offline no-current-season candidate')
    parser.add_argument('--football-card-display',action='store_true',help='Read rating from supplied local content for canonical card UI; no static data persisted')
    parser.add_argument('--football-catalog',type=Path,help='ID-only verified/candidate local content catalog for bounded roster experiments')
    parser.add_argument('--football-state',type=Path,help='Observed local ownership/sparse lineup state; no complete-team claim')
    parser.add_argument('--owned-item-candidate',type=Path,help='Bounded one-item diagnostic file; stable startup does not enable it')
    parser.add_argument("--active-squad-candidate",choices=["empty","persona"],help="Diagnostic response only; playable squad remains unproved")
    match_group=parser.add_mutually_exclusive_group()
    match_group.add_argument('--offline-create-match',dest='offline_create_match_candidate',action='store_const',const='clock',help='Verified offline CreateMatch: explicit local start timestamp; no match ID/results')
    match_group.add_argument('--offline-create-match-candidate',dest='offline_create_match_candidate',type=Path,help='Scoped explicit timestamp candidate; solved roster and season remain fixed')
    parser.add_argument('--profile-state',type=Path,help='Explicit local development profile; default preservation profile unchanged')
    parser.add_argument('--profile-plate-projection',type=Path,help='Isolated hash-pinned startup profile projection with zero award deltas only; no fixture XP')
    parser.add_argument('--inventory-mutations',action='store_true',help='Captured MoveCard placement and zero-value unassigned duplicate-player DiscardCard; no packs/rewards')
    parser.add_argument('--native-transfer-list',action='store_true',help='Explicit captured transfer storage; default off, no auctions or sales')
    parser.add_argument('--native-match-xp',action='store_true',help='Isolated prospective GameReport XP candidate through existing journal; zero coin terms, default off')
    parser.add_argument('--native-season-coins',action='store_true',help='Isolated prospective approved season coin bonus candidate through existing journal and normal wallet refresh; default off')
    parser.add_argument('--native-season-prize-display',action='store_true',help='Prospective versioned seasonCoins display projection; default off, requires native season coins')
    parser.add_argument('--native-report-end-identity',action='store_true',help='Report-bound Sim completion identity; normal use requires certified Sim-only release admission, default off')
    parser.add_argument('--native-played-report-end-identity',action='store_true',help='Source-first played report/session identity; normal use requires certified release admission, default off')
    parser.add_argument('--native-distinct-season-ids',action='store_true',help='Isolated prospective division season identities; default off, no historical migration')
    parser.add_argument('--native-match-session',action='store_true',help='Isolated source-bound OfflineMatchInfo session candidate only; no XP/reward grants, default off')
    parser.add_argument('--goal-event',action='store_true',help='ACK only captured native ScoreAGoal ReportEvent, no accomplishment/reward writes')
    parser.add_argument('--market-policy',type=Path,help='Isolated offline Transfer Market economy policy (MARKET-001..006); default off')
    parser.add_argument('--market-empty-control',action='store_true',help='Isolated captured415 empty default player search; no listings or transactions')
    parser.add_argument('--pack-catalog-empty-control',action='store_true',help='Diagnostic StorePackTypes purchase[] only; no pack definition, grant, open or account mutation')
    parser.add_argument("--revival-pack-state",type=Path,help="Explicit revival_policy catalog entitlements only; no Shop purchase")
    parser.add_argument('--store-product-overlay',type=Path,help='Read-only revival product policy merged with selected account catalog')
    parser.add_argument('--store-release',action='store_true',help='Explicit backed-up local twelve-pack Store deployment; no gameplay rewards')
    parser.add_argument('--gameplay-release',action='store_true',help='Explicit archived certified Sim XP/coin composition beside the Store; no automatic packs')
    parser.add_argument('--reward-release',action='store_true',help='Explicit backed-up certified atomic rewards and paid/source caption coexistence')
    parser.add_argument('--classic-pack-art',action='store_true',help='Isolated recovered StoreStyle art enum projection; default off')
    parser.add_argument('--native-paid-pack-presentation',action='store_true',help='Isolated prospective purchased-offer caption binding; default off')
    parser.add_argument('--native-consumable-display',action='store_true',help='Isolated original subtype/resource injury-misc display candidate; no effects; default off')
    parser.add_argument('--native-free-coins',action='store_true',help='Isolated captured empty-target FreeCoins231 redemption; requires explicit display and ApplyCard; default off')
    parser.add_argument('--native-free-packs',action='store_true',help='Captured739 unassigned Free Gold voucher redemption; explicit opt-in only')
    parser.add_argument('--native-free-silver-packs',action='store_true',help='Unassigned Free Silver voucher redemption; explicit opt-in beside Free Gold')
    parser.add_argument('--native-free-bronze-packs',action='store_true',help='Unassigned Free Bronze voucher candidate; explicit opt-in beside Free Gold, default off')
    parser.add_argument('--native-training-transfer-list',action='store_true',help='Captured745 supported training-item transfer storage; requires explicit transfer selector')
    parser.add_argument('--native-quick-sell',action='store_true',help='Captured single/bulk discard with authorized FIFA16approx valuation; explicit account only, default off')
    parser.add_argument('--native-player-formation',action='store_true',help='Isolated captured557 playerformation78 candidate; originalformation15 target delta; defaultoff')
    parser.add_argument("--club-inventory",action="store_true",help="Captured ClubSearch players from durable club-pile ownership")
    parser.add_argument('--native-club-statistics',action='store_true',help='Isolated captured club statistics/Inventory tile candidate; default off')
    parser.add_argument('--apply-card',action='store_true',help='Captured atomic GK training ApplyCard only')
    parser.add_argument("--native-simulation-discovery",action="store_true",help="Isolated stock Sim eligibility discovery only; no simulation result replies")
    parser.add_argument("--native-simulation-create-ack",action="store_true",help="Isolated captured366 empty CreateSim ACK candidate; PlaySim/results remain held")
    parser.add_argument("--native-simulation-play-ack",action="store_true",help="Isolated captured367 neutral PlaySim ACK; native result remains held")
    parser.add_argument("--native-simulation-end-ack",action="store_true",help="Isolated mapped neutral DestroySim ACK; original native season save only, no reward grants")
    parser.add_argument('--native-season-completion',action='store_true',help='Isolated durable native final-fixture completion and zero-award revival rollover; disabled by default')
    parser.add_argument('--native-match-reward-policy',type=Path,help='Explicit one-fixture isolated native coin policy (bounded test or approved division/result coins); default disabled')
    parser.add_argument('--native-match-pack-policy',type=Path,help='Explicit isolated prospective source-pack policy; default off')
    parser.add_argument('--native-source-pack-presentation',action='store_true',help='Isolated prospective typed caption reservations for new source packs; default off, no ownership grants')
    parser.add_argument('--native-atomic-matches',action='store_true',help='Isolated staged XP/coin quote; commit with genuine native season save in the existing journal; default off')
    parser.add_argument('--native-atomic-season-rewards',action='store_true',help='Isolated prospective combined final season reward images; disabled by default')
    parser.add_argument('--native-difficulty-rewards',action='store_true',help='Isolated prospective difficulty-based match XP/coins and scheduled season mean; default off')
    parser.add_argument('--native-early-season-completion',action='store_true',help='Isolated prospective secured-outcome payout/rollover; preserve unplayed fixtures and higher-outcome opportunities, default off')
    parser.add_argument('--native-played-matches',action='store_true',help='Isolated original played-match atomic XP/coin candidate; default off')
    parser.add_argument('--native-mixed-matches',action='store_true',help='Source-bound played and Sim rewards; normal account requires archived admission')
    parser.add_argument('--native-player-exchange-policy',type=Path,help='Explicit isolated original Player Exchange range-table candidate; mutations disabled')
    parser.add_argument('--offline-tournaments-sim',action='store_true',help='Isolated source-bound tournament simulation discovery, zero rewards')
    parser.add_argument('--offline-tournaments-rewards',type=Path,help='Explicit temporary championship coin revival policy (user 3 Nov 2026); default off')
    parser.add_argument('--offline-tournaments-start',action='store_true',help='Isolated1354 initial Starter Cup checkpoint only; no match/reward admission')
    parser.add_argument('--offline-tournaments-preview',type=Path,help='Archived isolated read-only TournamentList/catalog/metadata; no entry, gameplay or rewards')
    parser.add_argument('--native-player-exchange-start',action='store_true',help='Isolated source-bound original1338 Start candidate; normal account refused')
    parser.add_argument('--account-runtime-profile', type=Path,
                        help='Explicit completed first-run account, current Store/gameplay profile')
    args = parser.parse_args(argv)
    from server import fresh_account_runtime
    try:
        fresh_runtime = fresh_account_runtime.configure_arguments(args, parser)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))
    from server import market_protocol
    market_protocol.configure(args.profile_state.parent if args.market_policy and args.profile_state else None,args.market_policy)
    from server import native_tournament_catalog
    if args.offline_tournaments_preview and not args.profile_state:
        parser.error('Tournament preview requires explicit isolated profile')
    try:native_tournament_catalog.configure(args.profile_state.parent if args.offline_tournaments_preview else None,args.offline_tournaments_preview,start=args.offline_tournaments_start,sim=args.offline_tournaments_sim,rewards=args.offline_tournaments_rewards)
    except (ValueError,OSError,KeyError,TypeError) as error:parser.error(str(error))
    from server import native_player_exchange_protocol
    if args.native_player_exchange_policy and not args.profile_state:
        parser.error('Exchange candidate needs an explicit isolated profile')
    if args.native_player_exchange_start and not args.native_player_exchange_policy:
        parser.error('Exchange Start needs the explicit isolated range policy')
    try:native_player_exchange_protocol.configure(args.profile_state.parent if args.native_player_exchange_policy else None,args.native_player_exchange_policy,start=args.native_player_exchange_start)
    except (ValueError,OSError,KeyError,TypeError) as error:parser.error(str(error))
    from server import season_choice_preview
    season_choice_preview.configure()
    if sum((args.offline_season_choices_preview,args.offline_season_choices_start,args.offline_season_choices_gameplay,args.offline_season_choices_handoff,args.offline_season_choices_cycle)) > 1:
        parser.error('Choose read-only preview or explicit initial-save candidate')
    if args.native_season_prize_display and not args.native_season_coins:
        parser.error('Season prize display requires native season coins')
    if args.native_season_prize_display and args.profile_state and args.profile_state.parent.resolve()==Path(__file__).resolve().parent/'data/development/fm16in2026':
        if not args.reward_release:parser.error('Normal season prize display requires admitted rewards')
        try:
            from scripts.verify_season_prize_display import verify as verify_season_prize_display
            verify_season_prize_display()
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    if args.native_difficulty_rewards and not args.season_choice_release:
        if (not args.offline_season_choices_cycle or args.gameplay_release or args.reward_release
                or not args.native_atomic_matches or not args.native_match_xp
                or not args.native_season_coins or not args.native_atomic_season_rewards):
            parser.error('Difficulty rewards require isolated competition cycles with atomic XP/match/season coins')
    if args.offline_season_choices_preview or args.offline_season_choices_start or args.offline_season_choices_handoff:
        if (not args.profile_state or not args.offline_seasons_state or not args.offline_seasons_definition
                or args.gameplay_release or args.reward_release or args.native_season_completion
                or args.native_match_xp or args.native_match_session or args.offline_create_match_candidate
                or args.play_game or args.destroy_match or args.native_simulation_create_ack
                or args.native_simulation_play_ack or args.native_simulation_end_ack
                or args.native_match_reward_policy or args.native_match_pack_policy):
            parser.error('Season choices preview requires isolated read-only startup without gameplay/rewards')
        try:
            account=startup.validate_simulation_discovery([args.profile_state,args.football_state,args.football_catalog,args.revival_pack_state,args.offline_seasons_state,args.offline_seasons_definition,args.startup_control])
            season_choice_preview.configure(account,saves=args.offline_season_choices_start,handoff=args.offline_season_choices_handoff)
        except ValueError as error:parser.error(str(error))
    if args.offline_season_choices_gameplay or args.offline_season_choices_cycle:
        if (args.gameplay_release or args.reward_release or not args.native_season_completion
                or not args.native_atomic_matches or not args.native_match_xp
                or not args.native_match_session or not args.native_match_reward_policy
                or (args.native_season_coins and not args.offline_season_choices_cycle)):
            parser.error('Competition gameplay requires isolated atomic XP/coins; season rewards require cycle mode')
        try:
            if fresh_runtime:
                season_choice_preview.configure_fresh(args.profile_state.parent)
            else:
                season_choice_preview.validate_reward_composition(args.native_match_pack_policy,
                    cycle=args.offline_season_choices_cycle,source_presentation=args.native_source_pack_presentation,
                    season_coins=args.native_season_coins,atomic_season_rewards=args.native_atomic_season_rewards)
                account=startup.validate_simulation_discovery([args.profile_state,args.football_state,args.football_catalog,args.revival_pack_state,args.offline_seasons_state,args.offline_seasons_definition,args.startup_control])
                season_choice_preview.configure(account,gameplay=args.offline_season_choices_gameplay,cycle=args.offline_season_choices_cycle)
        except ValueError as error:parser.error(str(error))
    if args.native_early_season_completion and (not args.native_atomic_season_rewards or (args.gameplay_release and not args.reward_release)):
        parser.error('Early season completion requires explicit isolated atomic season rewards')
    if args.native_mixed_matches and (not args.native_atomic_matches or args.native_played_matches):
        parser.error('Mixed matches require atomic rewards without the played-only selector')
    if args.native_played_matches and (not args.native_atomic_matches or args.gameplay_release):
        parser.error('Played match candidate requires isolated atomic rewards; normal deployment refused')
    if args.native_atomic_season_rewards and (not args.native_atomic_matches or not args.native_season_coins or (args.gameplay_release and not args.reward_release)):
        parser.error('Atomic season rewards require explicit isolated atomic/season coin selectors')
    if args.native_atomic_matches and (not all((args.native_match_xp,args.native_match_session,args.native_season_completion,args.native_match_reward_policy)) or (args.native_season_coins and not args.native_atomic_season_rewards)):
        parser.error('Atomic matches require isolated XP/session/coin/completion selectors; unverified deployment refused')
    from server import gameplay_release
    gameplay_release.configure()
    if args.gameplay_release:
        required=(args.store_release,args.profile_state,args.native_match_xp,args.native_match_session,args.native_season_completion,
                  args.native_simulation_discovery,args.native_simulation_create_ack,args.native_simulation_play_ack,args.native_simulation_end_ack)
        if not all(required) or (args.native_match_pack_policy and not args.reward_release) or args.native_source_pack_presentation or args.market_empty_control or args.profile_plate_projection or args.native_player_formation:
            parser.error('Gameplay release requires complete certified XP/coin/Store selectors; unsupported modes refused')
        if args.native_match_reward_policy is None or args.native_match_reward_policy.resolve()!=Path(__file__).resolve().parents[1]/'server/policy/native-match-coins.json':parser.error('Gameplay release requires approved coin policy')
        try:gameplay_release.configure(args.profile_state.parent)
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
        from server.native_atomic_match import DEPLOYMENT,validate_deployment
        if (args.profile_state.parent/DEPLOYMENT).exists()!=args.native_atomic_matches:
            parser.error('Atomic deployment marker/runtime selector mismatch')
        if args.native_atomic_matches:
            try:validate_deployment(args.profile_state.parent)
            except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    from server import reward_release
    from server import native_pack_sessions
    if args.profile_state and args.profile_state.parent==native_pack_sessions.REAL and (args.profile_state.parent/native_pack_sessions.MARKER).exists()!=args.native_pack_sessions:parser.error('Pack-session admission/runtime mismatch')
    if args.revival_pack_state and args.revival_pack_state.exists() and json.loads(args.revival_pack_state.read_bytes()).get('identity_version')==native_pack_sessions.PRIVATE_VERSION and not args.native_pack_sessions:parser.error('Wide private packs require session presentation')
    native_pack_sessions.configure(args.profile_state.parent if args.native_pack_sessions else None)
    reward_release.configure()
    if args.reward_release:
        from server.native_match_pack_policy import STORE_PARITY_PATH
        if (not all((args.gameplay_release,args.store_release,args.native_paid_pack_presentation,
                args.native_atomic_matches,args.native_atomic_season_rewards,args.native_season_coins,
                args.native_early_season_completion,args.native_match_pack_policy)) or
                args.native_match_pack_policy.resolve()!=STORE_PARITY_PATH.resolve() or args.native_source_pack_presentation):
            parser.error('Reward release requires complete atomic Store-parity/early/paid gameplay composition')
        try:reward_release.configure(args.profile_state.parent)
        except (ValueError,OSError,KeyError,TypeError) as error:parser.error(str(error))
    elif args.gameplay_release and (args.profile_state.parent/reward_release.MARKER).exists():
        parser.error('Reward deployment/runtime selector mismatch')
    from server import season_choice_release
    season_choice_release.configure()
    if args.season_choice_release:
        if (not args.reward_release or not args.native_difficulty_rewards or args.offline_season_choices_cycle
                or args.native_source_pack_presentation):
            parser.error('Normal choices require certified compact rewards/difficulty and normal paid presentation')
        try:
            season_choice_release.configure(args.profile_state.parent)
            season_choice_preview.configure_release(args.profile_state.parent)
        except (ValueError,OSError,KeyError,TypeError) as error:parser.error(str(error))
    elif args.gameplay_release and (args.profile_state.parent/season_choice_release.MARKER).exists():
        parser.error('Choice deployment/runtime selector mismatch')
    from server import season_forfeit
    if args.native_pack_sessions and not (args.gameplay_release or fresh_runtime):parser.error('Pack sessions require complete gameplay/Store context')
    from server import native_match_forfeit
    native_match_forfeit.configure()
    if args.native_match_forfeit:
        if not (args.gameplay_release or fresh_runtime):parser.error('Match forfeiture requires certified match context')
        try:native_match_forfeit.configure(args.profile_state.parent)
        except (ValueError,OSError,KeyError,TypeError) as error:parser.error(str(error))
    season_forfeit.configure()
    if args.native_season_forfeit:
        if not (args.season_choice_release or fresh_runtime):parser.error('Forfeiture requires certified choice/reward composition')
        try:season_forfeit.configure(args.profile_state.parent)
        except (ValueError,OSError,KeyError,TypeError) as error:parser.error(str(error))
    elif args.season_choice_release and (args.profile_state.parent/'season-forfeit-release.json').exists():
        parser.error('Forfeit admission/runtime selector mismatch')
    if args.gameplay_release:
        from server.played_match_release import MARKER as PLAYED_MARKER,validate as validate_played_release
        if (args.profile_state.parent/PLAYED_MARKER).exists()!=args.native_mixed_matches:
            parser.error('Played deployment/runtime mismatch')
        if args.native_mixed_matches:
            try:validate_played_release(args.profile_state.parent)
            except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    if args.native_season_coins:
        if not (args.native_match_xp and args.native_match_session and args.native_season_completion and args.native_match_reward_policy):parser.error('Season coins require prospective native report and match coin source')
        if args.gameplay_release and not args.reward_release and gameplay_release.validate(args.profile_state.parent)['phase']!='candidate':parser.error('Uncertified season coins are isolated-only')
    if args.native_report_end_identity:
        if not (args.native_match_xp and args.native_match_session and args.native_season_completion):parser.error('Report identity requires genuine native XP/session/completion')
    if args.profile_state:
        from server.native_division_season_identity import REAL as IDENTITY_REAL,MARKER as IDENTITY_MARKER
        if (args.profile_state.parent.resolve()==IDENTITY_REAL and
            (IDENTITY_REAL/IDENTITY_MARKER).exists()!=args.native_distinct_season_ids):
            parser.error('Division identity deployment/runtime mismatch')
    if args.native_distinct_season_ids:
        identity_account=args.profile_state.parent.resolve() if args.profile_state else None
        if not args.native_atomic_matches or not args.native_season_completion or identity_account is None:
            parser.error('Distinct season IDs require an explicit atomic runtime')
        from server.native_division_season_identity import REAL as IDENTITY_REAL,validate_deployment
        if args.gameplay_release and (identity_account==IDENTITY_REAL or args.reward_release):
            validate_deployment(identity_account)
        elif not fresh_runtime and (args.gameplay_release or Path(__file__).resolve().parents[1]/'reports' not in identity_account.parents or identity_account.name!='isolated-account'):
            parser.error('Distinct season IDs require isolated or certified normal admission')
    if args.native_played_report_end_identity:
        account=args.profile_state.parent.resolve() if args.profile_state else None
        if (not all((args.native_match_xp,args.native_match_session,args.native_season_completion,args.native_atomic_matches))
                or not (args.native_mixed_matches or args.native_played_matches) or account is None):
            parser.error('Played report identity requires isolated atomic native XP/session/played context')
        isolated=Path(__file__).resolve().parents[1]/'reports' in account.parents and account.name=='isolated-account'
        if not isolated and not fresh_runtime:
            from server import played_identity_release
            if not args.gameplay_release:parser.error('Played report identity requires isolated atomic context or certified gameplay release')
            try:played_identity_release.validate(account)
            except (ValueError,OSError,KeyError) as error:parser.error('Played report identity requires isolated atomic context or valid release: '+str(error))
    if args.gameplay_release:
        from server import sim_completion_release
        marked=(args.profile_state.parent/sim_completion_release.MARKER).exists()
        if marked!=args.native_report_end_identity and (marked or gameplay_release.validate(args.profile_state.parent)['phase']!='candidate'):
            parser.error('Sim completion deployment/runtime mismatch')
        if marked:
            if not args.native_atomic_matches:parser.error('Sim completion release requires atomic matches')
            try:sim_completion_release.validate(args.profile_state.parent)
            except (ValueError,OSError,KeyError) as error:parser.error(str(error))
        from server import played_identity_release
        if (args.profile_state.parent/played_identity_release.MARKER).exists()!=args.native_played_report_end_identity and args.profile_state.parent==played_identity_release.REAL:
            parser.error('Played identity deployment/runtime mismatch')
    from server import store_release
    store_release.configure()
    if args.store_release:
        if not args.gameplay_release and any((args.profile_plate_projection,args.native_player_formation,args.native_match_reward_policy,args.native_match_pack_policy,args.native_source_pack_presentation,args.native_season_completion,args.native_simulation_discovery,args.market_empty_control)):
            parser.error('Store deployment excludes experimental gameplay/reward selectors')
        if not (args.profile_state and args.classic_pack_art and args.native_paid_pack_presentation and args.native_consumable_display):parser.error('Store deployment requires proven artwork/captions/display')
        try:store_release.configure(args.profile_state.parent)
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    from server.native_club_statistics import configure as configure_club_statistics
    configure_club_statistics()
    if args.native_club_statistics:
        if not args.club_inventory:parser.error('Club statistics require club inventory')
        try:
            account=startup.validate_simulation_discovery([args.profile_state,args.football_state,args.football_catalog,args.revival_pack_state,args.offline_seasons_state,args.offline_seasons_definition,args.startup_control])
            configure_club_statistics(account)
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    from server.football_protocol import configure_consumable_display
    if args.native_consumable_display:
        try:
            from server.native_match_pack_policy import validate_consumable_display_integration
            validate_consumable_display_integration(
                args.native_match_pack_policy,
                source_presentation=args.native_source_pack_presentation,
                account=args.profile_state.parent if args.profile_state else None,
            )
            account=store_release.projection_account([args.profile_state,args.football_state,args.football_catalog,args.revival_pack_state,args.offline_seasons_state,args.offline_seasons_definition,args.startup_control])
            configure_consumable_display(account)
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    else:configure_consumable_display()
    from server.apply_card import configure_player_formation
    from server.consumable_effects import configure as configure_consumable_effects
    configure_consumable_effects(args.profile_state.parent if args.apply_card and args.profile_state else None)
    from server.club_item_actions import configure as configure_club_item_actions
    configure_club_item_actions(args.profile_state.parent if args.club_inventory and args.profile_state else None)
    if args.profile_state and (args.profile_state.parent/'consumable-effects-release.json').exists() and not (args.apply_card and args.native_consumable_display):
        parser.error('Consumable effect admission requires original display and ApplyCard')
    from server import consumable_effects
    if consumable_effects.POLICY and 'training' in consumable_effects.POLICY['features'] and not args.native_atomic_matches:
        parser.error('One-game training requires the atomic match coordinator')
    if consumable_effects.POLICY and 'healing' in consumable_effects.POLICY['features'] and not args.native_atomic_matches:
        parser.error('Healing requires atomic native injury persistence')
    if args.native_player_formation:
        if not (args.native_consumable_display and args.apply_card) or args.native_season_completion:
            parser.error('Player formation requires isolated display/ApplyCard without match completion')
        try:configure_player_formation(args.profile_state.parent)
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    else:configure_player_formation()
    from server.native_transfer_list import configure as configure_transfer_list
    configure_transfer_list()
    if args.native_training_transfer_list and not args.native_transfer_list:parser.error('Training transfer requires player transfer selector')
    if args.native_transfer_list:
        if not args.inventory_mutations:parser.error('Transfer storage requires inventory mutations')
        try:configure_transfer_list(args.profile_state.parent,training=args.native_training_transfer_list)
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    from server import native_free_coins_protocol
    native_free_coins_protocol.configure()
    if args.native_free_coins:
        if not (args.native_consumable_display and args.apply_card) or (args.native_season_completion and not (args.gameplay_release or fresh_runtime)):
            parser.error('FreeCoins requires isolated consumable display and ApplyCard without match completion')
        try:
            from server.native_free_coins import FreeCoinsCoordinator
            native_free_coins_protocol.configure(FreeCoinsCoordinator(args.profile_state.parent,enabled=True))
            native_free_coins_protocol.recover(args.football_state)
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    from server.native_pack_art import configure as configure_pack_art
    if args.classic_pack_art:
        try:
            account=store_release.projection_account([args.profile_state,args.football_state,args.football_catalog,args.revival_pack_state,args.offline_seasons_state,args.offline_seasons_definition,args.startup_control])
            configure_pack_art(account)
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    else:configure_pack_art()
    from server.native_paid_pack_presentation import configure as configure_paid_presentation
    if args.native_paid_pack_presentation:
        if args.native_match_pack_policy and not (args.reward_release or fresh_runtime):parser.error('Paid presentation cannot combine with unverified automatic reward-pack routing')
        try:
            account=store_release.projection_account([args.profile_state,args.football_state,args.football_catalog,args.revival_pack_state,args.offline_seasons_state,args.offline_seasons_definition,args.startup_control])
            configure_paid_presentation(account)
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    else:configure_paid_presentation()
    from server.native_source_pack_presentation import configure as configure_source_presentation
    if args.native_source_pack_presentation:
        if not args.profile_state or not args.native_match_pack_policy or not args.native_match_reward_policy or not args.classic_pack_art or args.native_paid_pack_presentation:
            parser.error('Source presentation requires explicit isolated match packs/coins/art and excludes paid presentation')
        try:
            configure_source_presentation(args.profile_state.parent)
            from server.native_source_pack_presentation import validate_reward_policy
            validate_reward_policy(args.native_match_pack_policy)
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    else:configure_source_presentation()
    if args.native_match_pack_policy and not args.native_match_reward_policy:parser.error('Native packs require isolated approved coin policy')
    if args.native_match_xp and (not args.native_match_session or args.profile_plate_projection):parser.error('Native XP candidate requires isolated session and earned profile, without pinned projection')
    if args.native_match_session and not args.native_season_completion:parser.error('Match session candidate requires isolated native completion')
    if args.native_match_reward_policy and not args.native_season_completion:parser.error('Native test rewards require isolated durable native completion coordinator')
    if args.native_season_completion and not (args.native_simulation_end_ack and args.offline_season_policy):parser.error('Native completion requires isolated native Sim and v2 policy')
    if args.native_simulation_end_ack and not args.native_simulation_play_ack:parser.error("DestroySim ACK requires isolated PlaySim ACK")
    if args.native_simulation_play_ack and not args.native_simulation_create_ack:parser.error("PlaySim ACK requires isolated CreateSim ACK")
    if args.native_simulation_create_ack and not args.native_simulation_discovery:parser.error("CreateSim ACK requires isolated discovery")
    if args.native_simulation_discovery or args.market_empty_control:
        if not args.settings:parser.error("Simulation discovery requires startup settings")
        try:
            (fresh_account_runtime.validate_selectors if fresh_runtime else gameplay_release.validate_selectors if args.gameplay_release else startup.validate_simulation_discovery)([args.profile_state,args.football_state,args.football_catalog,args.revival_pack_state,args.offline_seasons_state,args.offline_seasons_definition,args.startup_control])
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    from server import native_free_packs, native_free_packs_protocol
    native_free_packs_protocol.configure();native_free_packs.configure()
    if (args.native_free_silver_packs or args.native_free_bronze_packs) and not args.native_free_packs:
        parser.error('Free Silver requires the existing Free Pack coordinator')
    if args.native_free_packs:
        if not (args.native_consumable_display and args.apply_card and args.native_paid_pack_presentation and args.classic_pack_art) or (args.native_season_completion and not (args.gameplay_release or fresh_runtime)):
            parser.error('Free pack redemption requires supported Store/display/ApplyCard without match completion')
        try:
            native_free_packs_protocol.configure(native_free_packs.configure(args.profile_state.parent,silver=args.native_free_silver_packs,bronze=args.native_free_bronze_packs))
            native_free_packs_protocol.recover(args.football_state)
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    from server import native_quick_sell_protocol
    native_quick_sell_protocol.configure()
    if args.native_quick_sell:
        if not (args.inventory_mutations and args.native_consumable_display) or (args.native_season_completion and not (args.gameplay_release or fresh_runtime)):
            parser.error('Quick sell requires supported Store inventory/display without match completion')
        try:
            from server.native_quick_sell import QuickSellCoordinator
            native_quick_sell_protocol.configure(QuickSellCoordinator(args.profile_state.parent,enabled=True))
            native_quick_sell_protocol.recover(args.football_state)
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    if args.offline_season_policy:
        if not (args.offline_seasons_state and args.offline_seasons_definition):parser.error("Season policy requires explicit season state and definition")
        from server.season_revival_policy import load_policy
        load_policy(args.offline_season_policy)
    if args.store_product_overlay and not args.revival_pack_state:parser.error('Store product overlay requires explicit pack state')
    from server.local_store import configure_product_overlay
    configure_product_overlay(args.store_product_overlay)
    if args.apply_card and not args.football_state:parser.error('ApplyCard requires explicit football state')
    if args.club_inventory and not args.football_state:parser.error("Club inventory requires explicit football state")
    if args.squad_mutations and not (args.save_squad and args.football_state):parser.error('Squad mutations require --save-squad and explicit --football-state')
    if args.squad_management and not (args.squad_mutations and args.squad_list_candidate):parser.error('Squad management requires squad mutation/navigation selectors')
    from server.squad_management import configure as configure_squad_management
    configure_squad_management(args.football_state.parent if args.squad_management else None)
    if args.inventory_mutations and not args.football_state:parser.error('Inventory mutations require explicit --football-state')
    if args.profile_state:
        from server.local_profile import configure_profile,load_profile
        configure_profile(args.profile_state);load_profile()
    if args.profile_plate_projection:
        if not args.victory_session:parser.error('Profile projection needs original Victory startup contract')
        try:
            startup.validate_simulation_discovery([args.profile_state,args.football_state,args.football_catalog,args.revival_pack_state,args.offline_seasons_state,args.offline_seasons_definition,args.startup_control])
            victory_session.configure_plate_projection(args.profile_plate_projection,args.profile_state)
        except (ValueError,OSError,KeyError) as error:parser.error(str(error))
    victory_session.configure_earned_xp(args.profile_state if args.native_match_xp else None)
    if args.revival_pack_state:
        if not args.football_state:parser.error("Revival packs require an explicit football store")
        from server.local_packs import PackStore
        from server.local_football import FootballStore
        from server.local_content import ContentCatalog
        from server.pack_protocol import recover_transactions
        from server.first_run_account import pending_session
        if pending_session(args.profile_state.parent) is None:
            recover_transactions(PackStore(args.revival_pack_state),FootballStore(args.football_state,ContentCatalog(args.football_catalog)))
    if args.native_season_completion:
        from server.native_season_completion import NativeSeasonCoordinator
        NativeSeasonCoordinator(args.profile_state.parent,enabled=True,reward_policy=args.native_match_reward_policy,match_pack_policy=args.native_match_pack_policy,native_match_xp=args.native_match_xp,backend_report_bound_end_identity=args.native_report_end_identity,backend_season_coin_rewards=args.native_season_coins,backend_season_awards_projection=args.native_season_coins,native_atomic_matches=args.native_atomic_matches,native_played_matches=args.native_played_matches,native_mixed_matches=args.native_mixed_matches,backend_played_report_bound_end_identity=args.native_played_report_end_identity,backend_distinct_season_ids=args.native_distinct_season_ids,backend_atomic_season_rewards=args.native_atomic_season_rewards,native_early_season_completion=args.native_early_season_completion,backend_difficulty_rewards=args.native_difficulty_rewards,backend_season_prize_display=args.native_season_prize_display).initialize()
    if fresh_runtime:
        from server.mobile_setup_session import promote
        promote(args.profile_state.parent)
    return args


def main(argv=None, *, stop_event=None, on_ready=None, local_transport=False, runtime_update=None):
    args = configure_runtime(argv)
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', args.port))
        listener.listen()
        if stop_event is not None:
            listener.settimeout(0.25)
        if on_ready is not None:
            on_ready(listener.getsockname()[1])
        workers = []
        while stop_event is None or not stop_event.is_set():
            try:
                conn, peer = listener.accept()
            except socket.timeout:
                continue
            if runtime_update is not None:
                # First-run handoff is exclusive: finish accepted setup replies
                # before reconfiguring shared adapters. Keep the listener bound.
                for active in workers:
                    active.join()
                replacement = runtime_update()
                if replacement is not None:
                    args = configure_runtime(replacement)
                    runtime_update = None
            worker = threading.Thread(
                target=handle,
                args=(
                    conn,
                    peer,
                    args.output,
                    args.persona_id,
                    args.fut_auth_code,
                    args.victory_auth_code,
                    args.game_session,
                    args.startup_control,
                    args.settings,
                    args.match_reset_candidate,
                    args.user_info_candidate,
                    args.purchased_items,
                    args.victory_session,
                    args.finalize_authentication,
                    args.finalize_queue_prerequisites,
                    args.user_credits,
                    args.active_squad_candidate,
                    args.owned_item_candidate,
                    args.football_state,
                    args.staff_bonuses,
                    args.squad_list_candidate,
                    args.football_catalog,
                    args.football_card_display,
                    args.offline_season_candidate,
                    args.offline_current_candidate,
                    args.offline_seasons_state,
                    args.offline_seasons_definition,
                    args.offline_create_match_candidate,
                    args.persona_accomplishments,
                    args.save_squad,
                    args.cycle_session,
                    args.play_game,
                    args.destroy_match,
                    args.squad_mutations,
                    args.goal_event,
                    args.inventory_mutations,
                    args.pack_catalog_empty_control,
                    args.revival_pack_state,
                    args.club_inventory,
                    args.apply_card,
                    args.offline_season_policy,
                    args.native_simulation_discovery,
                    args.native_simulation_create_ack,
                    args.native_simulation_play_ack,
                    args.native_simulation_end_ack,
                    args.native_season_completion,
                    args.native_match_reward_policy,
                    args.market_empty_control,
                    args.native_match_pack_policy,
                    args.native_match_session,
                    args.native_match_xp,
                    args.native_report_end_identity,
                    args.native_season_coins,
                    args.native_atomic_matches,
                    args.native_played_matches,
                    args.native_mixed_matches,
                    args.native_played_report_end_identity,
                    args.native_distinct_season_ids,
                    args.native_atomic_season_rewards,
                    args.native_early_season_completion,
                    args.native_difficulty_rewards,
                    args.native_season_prize_display,
                ),
                kwargs={'local_transport': True} if local_transport else {},
                daemon=True,
            )
            worker.start()
            if stop_event is not None or runtime_update is not None:
                workers = [thread for thread in workers if thread.is_alive()]
                workers.append(worker)
        # An explicit launcher stop stops accepting connections, then waits for
        # already accepted handlers to finish their existing transaction rules.
        for worker in workers:
            worker.join()

if __name__ == '__main__':
    main()
