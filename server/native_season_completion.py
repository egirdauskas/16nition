"""Opt-in isolated native season lifecycle, rollover and bounded test coin commit.

Private account/cycle/fixture receipts are server-owned, never wire match IDs.
Only an accepted CreateSim -> PlaySim -> genuine DestroySim can finish a cycle.
Original opaque bytes are archived, not generated. A new cycle starts empty and
must receive the original client's genuine round-one save before another match.
"""
from contextlib import contextmanager
from dataclasses import asdict
import copy,fcntl,hashlib,json,os,tempfile,uuid
from pathlib import Path
from .local_seasons import SeasonStore,load_definition
from .local_profile import load_profile
from .local_football import FootballStore
from .local_content import ContentCatalog
from .native_simulation_protocol import inspect_create,inspect_end,play_ack,CREATE_PATH,END_PATH
from .season_revival_policy import load_policy
from .account_transaction import atomic, recover_images
from .store_release import reuse_store_validation

def digest(data):return hashlib.sha256(data).hexdigest()
def encode(value):return (json.dumps(value,indent=2,sort_keys=True)+'\n').encode()
class NativeSeasonCoordinator:
    @reuse_store_validation
    def __init__(self,account,*,enabled=False,fault=None,reward_policy=None,backend_progression=False,backend_pack_entitlements=False,backend_fixture_pack_definition=None,match_pack_policy=None,backend_season_coin_rewards=False,backend_championship_pack_definition=None,backend_approved_match_packs=False,backend_all_tier_specials=False,backend_expanded_consumables=False,backend_filtered_consumables=False,backend_exclude_capacity_crowd=False,native_match_xp=False,backend_report_bound_end_identity=False,backend_season_awards_projection=False,backend_season_prize_display=False,native_atomic_matches=False,native_played_matches=False,native_mixed_matches=False,backend_played_report_bound_end_identity=False,backend_distinct_season_ids=False,backend_atomic_season_rewards=False,native_early_season_completion=False,backend_compact_pack_records=False,backend_difficulty_rewards=False):
        if enabled is not True:raise ValueError('Native completion disabled by default')
        if type(native_match_xp) is not bool:raise ValueError('Explicit native XP selector required')
        if native_match_xp and (backend_progression or backend_approved_match_packs):raise ValueError('Cannot combine native and backend-only XP progression')
        self.native_match_xp=native_match_xp
        if type(backend_report_bound_end_identity) is not bool or (backend_report_bound_end_identity and not native_match_xp):raise ValueError('Report-bound identity requires explicit backend candidate and native XP report')
        self.backend_report_bound_end_identity=backend_report_bound_end_identity
        self.account=Path(account).resolve();root=Path(__file__).resolve().parents[1]
        from .fresh_account_runtime import selected as fresh_selected
        fresh = fresh_selected(self.account)
        if type(backend_played_report_bound_end_identity) is not bool:
            raise ValueError('Explicit played report-bound identity selector required')
        if backend_played_report_bound_end_identity:
            from . import gameplay_release
            isolated=root/'reports' in self.account.parents and self.account.name=='isolated-account'
            if (not native_match_xp or not native_atomic_matches or not (native_played_matches or native_mixed_matches)
                    or (not isolated and not fresh and not gameplay_release.selected(self.account))):
                raise ValueError('Played report-bound identity requires isolated atomic native XP/played context or certified release')
            if not isolated and not fresh:
                from .played_identity_release import validate
                validate(self.account)
        self.backend_played_report_bound_end_identity=backend_played_report_bound_end_identity
        from . import gameplay_release
        released=gameplay_release.selected(self.account)
        from . import reward_release
        reward_released=reward_release.selected(self.account)
        if reward_released:reward_release.validate(self.account)
        if type(backend_distinct_season_ids) is not bool:
            raise ValueError('Explicit distinct season identity selector required')
        if backend_distinct_season_ids:
            if not native_atomic_matches:raise ValueError('Distinct season IDs require explicit isolated atomic admission')
            if released:
                from .native_division_season_identity import validate_deployment
                validate_deployment(self.account)
            elif not fresh and (root/'reports' not in self.account.parents or self.account.name!='isolated-account'):
                raise ValueError('Distinct season IDs require explicit isolated atomic admission')
        self.backend_distinct_season_ids=backend_distinct_season_ids
        if released:gameplay_release.validate(self.account)
        if released and backend_report_bound_end_identity:
            from . import sim_completion_release
            if (self.account/sim_completion_release.MARKER).exists() or gameplay_release.validate(self.account)['phase']!='candidate':
                sim_completion_release.validate(self.account)
        if not released and not fresh and (root/'reports' not in self.account.parents or self.account.name!='isolated-account'):
            raise ValueError('Disposable reports account required; real account refused')
        if not released and not fresh and not (self.account/'.lab-snapshot.json').is_file():raise ValueError('Isolation archive required')
        for file in self.account.glob('*.json'):
            if file.is_symlink():raise ValueError('Account alias refused')
            real=root/'server/data/development/fm16in2026'/file.name
            if self.account!=real.parent and real.exists() and file.samefile(real):raise ValueError('Real file alias refused')
        self.path=self.account/'native-seasons.json';self.fault=fault
        if type(backend_season_coin_rewards) is not bool:raise ValueError('Explicit backend season coin selector required')
        self.backend_season_coin_rewards=backend_season_coin_rewards
        if type(backend_season_awards_projection) is not bool or (backend_season_awards_projection and not backend_season_coin_rewards):raise ValueError('Native season Awards require explicit season coin candidate')
        self.backend_season_awards_projection=backend_season_awards_projection
        if type(backend_season_prize_display) is not bool or (backend_season_prize_display and not backend_season_awards_projection):raise ValueError('Season prize display requires explicit Awards projection')
        self.backend_season_prize_display=backend_season_prize_display
        if type(backend_pack_entitlements) is not bool:raise ValueError('Explicit backend entitlement selector required')
        if type(backend_approved_match_packs) is not bool:raise ValueError('Explicit backend approved pack selector required')
        self.backend_approved_match_packs=backend_approved_match_packs
        if type(backend_all_tier_specials) is not bool or (backend_all_tier_specials and not backend_approved_match_packs):raise ValueError('All-tier special quotes require explicit backend approved pack mode')
        self.backend_all_tier_specials=backend_all_tier_specials
        if type(backend_expanded_consumables) is not bool or (backend_expanded_consumables and not backend_all_tier_specials):raise ValueError('Expanded consumables require explicit backend all-tier special mode')
        self.backend_expanded_consumables=backend_expanded_consumables
        if type(backend_filtered_consumables) is not bool or (backend_filtered_consumables and not backend_expanded_consumables):raise ValueError('Filtered consumables require explicit backend expanded mode')
        self.backend_filtered_consumables=backend_filtered_consumables
        if type(backend_exclude_capacity_crowd) is not bool or (backend_exclude_capacity_crowd and not backend_filtered_consumables):raise ValueError('Capacity Crowd exclusion requires explicit backend filtered mode')
        self.backend_exclude_capacity_crowd=backend_exclude_capacity_crowd
        if backend_approved_match_packs and (match_pack_policy is not None or backend_fixture_pack_definition is not None):raise ValueError('Cannot combine distinct match pack policies')
        self.atomic_pack_policy=None
        if native_atomic_matches and match_pack_policy is not None:
            from .native_match_pack_policy import PATH_V6,STORE_PARITY_PATH
            if (released and not reward_released) or Path(match_pack_policy).resolve() not in (PATH_V6.resolve(),STORE_PARITY_PATH.resolve()):
                raise ValueError('Atomic packs require isolated explicit supported policy')
            if reward_released and Path(match_pack_policy).resolve()!=STORE_PARITY_PATH.resolve():raise ValueError('Released rewards require Store parity policy')
            self.atomic_pack_policy=Path(match_pack_policy)
            # Atomic packs use the combined journal image, never legacy delivery.
            match_pack_policy=None
        if type(backend_compact_pack_records) is not bool:raise ValueError('Explicit compact pack selector required')
        admitted_compact=reward_release.compact_records(self.account)
        if backend_compact_pack_records and (not native_atomic_matches or self.atomic_pack_policy is None or (released and not admitted_compact)):
            raise ValueError('Compact pack references require isolated atomic packs or certified admission')
        self.compact_pack_records=bool(admitted_compact or backend_compact_pack_records)
        self.match_pack_policy=match_pack_policy
        if match_pack_policy is not None:
            if backend_fixture_pack_definition is not None:raise ValueError('Cannot combine distinct pack policies')
            from .native_match_pack_policy import snapshot
            snapshot(10,match_pack_policy)
        self.has_match_pack_policy=match_pack_policy is not None or backend_approved_match_packs
        self.backend_pack_entitlements=backend_pack_entitlements or self.has_match_pack_policy
        self.championship_pack_definition=backend_championship_pack_definition
        if match_pack_policy is not None:
            from .native_match_pack_policy import championship_definition
            selected_title=championship_definition(load_definition(self.account/'definition.json').division_index,match_pack_policy)
            if selected_title is not None:
                if backend_championship_pack_definition is not None:raise ValueError('Cannot combine explicit native and backend title policies')
                self.championship_pack_definition=selected_title
        if backend_championship_pack_definition is not None and not self.backend_pack_entitlements:raise ValueError('Explicit source entitlement mode required for title packs')
        self.fixture_pack_delivery=None
        if backend_fixture_pack_definition is not None:
            if not backend_pack_entitlements:raise ValueError('Explicit backend source entitlement mode required')
            from .local_packs import DEFINITIONS
            if type(backend_fixture_pack_definition) is not str or backend_fixture_pack_definition not in DEFINITIONS:raise ValueError('Unsupported fixture pack definition; no label substitution')
            self.fixture_pack_delivery={'definition':backend_fixture_pack_definition,
                'definition_sha256':digest(encode(DEFINITIONS[backend_fixture_pack_definition])),
                'classification':'isolated_transport_test'}
        from .native_match_reward_policy import load_reward_policy
        self.reward_policy=load_reward_policy(reward_policy) if reward_policy is not None else None
        if native_match_xp and self.reward_policy is not None and self.reward_policy['version']!='native_match_coins_v1':raise ValueError('Native XP requires approved coins, not the bounded test policy')
        self.coin_rewards=bool(self.reward_policy and self.reward_policy['version']=='native_match_coins_v1')
        from . import season_choice_release
        self.released_choices=season_choice_release.selected(self.account)
        if (type(backend_difficulty_rewards) is not bool or (backend_difficulty_rewards and
                ((released and not self.released_choices) or not native_atomic_matches or not native_match_xp or not self.coin_rewards))):
            raise ValueError('Difficulty rewards require explicit isolated atomic backend mode')
        self.backend_difficulty_rewards=backend_difficulty_rewards
        if type(native_atomic_matches) is not bool:raise ValueError('Explicit atomic match selector required')
        if native_atomic_matches and (not native_match_xp or not self.coin_rewards or backend_progression or self.backend_pack_entitlements or self.championship_pack_definition is not None or (backend_season_coin_rewards and not backend_atomic_season_rewards)):
            raise ValueError('Atomic match candidate requires native XP/approved coins without separate pack/season transactions')
        if type(backend_atomic_season_rewards) is not bool or (backend_atomic_season_rewards and
                (not native_atomic_matches or not backend_season_coin_rewards or (released and not reward_released))):
            raise ValueError('Atomic season rewards require explicit isolated certification')
        self.backend_atomic_season_rewards=backend_atomic_season_rewards
        if type(native_early_season_completion) is not bool or (native_early_season_completion and
                (not backend_atomic_season_rewards or not native_atomic_matches or (released and not reward_released))):
            raise ValueError('Early season completion requires explicit isolated atomic season rewards')
        self.native_early_season_completion=native_early_season_completion
        if native_atomic_matches and released:
            from .native_atomic_match import validate_deployment
            validate_deployment(self.account)
        if type(native_played_matches) is not bool or (native_played_matches and (released or not native_atomic_matches)):
            raise ValueError("Played match candidate requires isolated atomic native rewards")
        if type(native_mixed_matches) is not bool or (native_mixed_matches and (native_played_matches or not native_atomic_matches)):
            raise ValueError('Mixed matches require atomic rewards and a distinct explicit selector')
        if native_mixed_matches and released:
            from .played_match_release import validate
            validate(self.account)
        self.native_mixed_matches=native_mixed_matches
        self.native_played_matches=native_played_matches
        self.native_atomic_matches=native_atomic_matches
        if backend_season_awards_projection and not self.coin_rewards:raise ValueError('Native season Awards require approved match coin fields')
        if self.has_match_pack_policy and not self.coin_rewards:raise ValueError('Approved source packs require approved coin policy')
        if type(backend_progression) is not bool:raise ValueError('Explicit backend progression selector required')
        if backend_progression and reward_policy is not None:raise ValueError('Do not combine distinct reward policies')
        from .account_progression import load_progression_policy
        # No reachability/mobile endpoint enables this backend certification mode.
        self.progression_policy=load_progression_policy() if backend_progression else None
        self.policy=load_policy()
        if self.policy.version!='offline_seasons_console_fifa16_v2':raise ValueError('Wrong authorized policy')
    def difficulty_mode(self,state):
        if self.released_choices:
            from .season_choice_release import difficulty_enabled
            return self.backend_difficulty_rewards and difficulty_enabled(self.account,state)
        return self.backend_difficulty_rewards
    def _pack_snapshot(self,division):
        from .native_match_pack_policy import snapshot,backend_snapshot
        if self.backend_approved_match_packs:return backend_snapshot(division,specials=self.backend_all_tier_specials,expanded_consumables=self.backend_expanded_consumables,filtered_consumables=self.backend_filtered_consumables,exclude_capacity_crowd=self.backend_exclude_capacity_crowd)
        return snapshot(division,self.match_pack_policy) if self.match_pack_policy is not None else None
    def _check_pack_capacity(self,count):
        if not count:return
        if getattr(self,'backend_atomic_season_rewards',False) and self.atomic_pack_policy:
            season,_=self.stores();current=season.load()
            if current and (current.round_number==10 or getattr(self,'native_early_season_completion',False)):
                from .native_match_pack_policy import championship_definition
                possible_title=(championship_definition(current.division_index,self.atomic_pack_policy) is not None and
                    self.policy.for_division(current.division_index).evaluate(10,current.user_points+3)['preview_band']=='CHAMPIONSHIP')
                count=max(count,1+int(possible_title))
        from .local_packs import PackStore
        value=PackStore(self.account/'packs.json').load()
        if value.get('prepared'):raise ValueError('Recover existing opening before automatic pack reward')
        from .local_packs import private_limit
        if value['next_catalog_id']+count>private_limit(value)+1:raise ValueError('Automatic pack reward allocator exhausted')
        from .native_source_pack_presentation import validate_capacity
        validate_capacity(PackStore(self.account/'packs.json'),count)
        from .reward_release import validate_capacity as release_capacity
        required=None
        from .reward_release import selected as reward_selected,POLICY as release_policy
        from .fresh_account_runtime import selected as fresh_selected
        if fresh_selected(self.account) or (reward_selected(self.account) and 'capacity' in release_policy):
            from .native_match_pack_policy import snapshot,championship_definition
            from collections import Counter
            season,_=self.stores();division=season.load().division_index
            quote=snapshot(division,self.atomic_pack_policy)
            title=championship_definition(division,self.atomic_pack_policy) if count>1 else None
            required={}
            for pick in quote['outcomes'].values():
                for definition,n in Counter([pick['definition']]+([title] if title else [])).items():
                    required[definition]=max(required.get(definition,0),n)
        release_capacity(PackStore(self.account/'packs.json'),count,required)
    @contextmanager
    def locked(self):
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
            # Serialize supported ProfileStore wallet mutations with the journal.
            # Mobile account operations also hold reachability.ACCOUNT_LOCK.
            try:
                # PurchaseStore uses packs then profile. Keep that same order
                # for explicit backend source-entitlement tests across processes.
                from .local_packs import PackStore
                with PackStore(self.account/'packs.json').transaction(), (self.account/'profile.json.lock').open('a') as profile_lock:
                    fcntl.flock(profile_lock.fileno(),fcntl.LOCK_EX)
                    try:yield
                    finally:fcntl.flock(profile_lock.fileno(),fcntl.LOCK_UN)
            finally:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)
    def stores(self):
        definition=load_definition(self.account/'definition.json')
        return SeasonStore(self.account/'seasons.json',definition),FootballStore(self.account/'football.json',ContentCatalog(self.account/'content.json'))
    def _load(self):
        value=json.loads(self.path.read_text())
        expected={'schema','account_id','account_identity','policy_version','cycle','active_match','matches','completions','prepared'}
        if set(value)-{'season_coin_rewards','aborted_matches','season_definition_history','season_forfeitures'}!=expected or type(value['schema']) is not int or value['schema']!=1 or value['account_identity']!=self.identity():raise ValueError('Wrong journal/account identity')
        from .season_forfeit import validate as validate_forfeitures
        validate_forfeitures(value)
        from .season_choice_reference import validate_history
        validate_history(value)
        if value['policy_version']!=self.policy.version:raise ValueError('Journal policy mismatch')
        uuid.UUID(value['account_id']);uuid.UUID(value['cycle']['id'])
        if value['cycle']['status'] not in ('active','awaiting_native_initialization'):raise ValueError('Invalid cycle status')
        if type(value['matches']) is not list or type(value['completions']) is not list:raise ValueError('Invalid receipt collection')
        if len({m['id'] for m in value['matches']})!=len(value['matches']) or len({c['cycle_id'] for c in value['completions']})!=len(value['completions']):raise ValueError('Duplicate native receipt/completion')
        if self.native_atomic_matches and value['active_match'] and bool(value['active_match'].get('atomic_pack'))!=bool(self.atomic_pack_policy):
            raise ValueError('Cannot change atomic pack mode during accepted match')
        if value['active_match'] and bool(value['active_match'].get('season_completion_timing'))!=self.native_early_season_completion:
            raise ValueError('Cannot change season completion timing during accepted match')
        from .native_played_protocol import validate_source
        for source in value["matches"]+value.get("aborted_matches",[])+([value["active_match"]] if value["active_match"] else []):validate_source(source)
        reward_view=value
        # Selection may have installed its definition image before interruption.
        # Validate the intent first and use its proven old-cycle archive while
        # checking receipts; the journal itself remains unchanged until recovery.
        if value['prepared'] is not None:
            from .season_choice_start import validate_intent as choice_intent
            pending=value['prepared']
            if choice_intent(value,pending['state_after'],pending['images']):
                self._validate_intent(value,pending)
                reward_view=copy.deepcopy(value)
                if 'season_definition_history' in pending['state_after']:
                    reward_view['season_definition_history']=pending['state_after']['season_definition_history']
        self._validate_rewards(reward_view)
        from .native_season_coin_rewards import validate as validate_season_coins
        validate_season_coins(value)
        from .native_championship_packs import validate as validate_title_packs
        validate_title_packs(value)
        if value['prepared'] is not None:
            prepared=value['prepared'];images=prepared['images']
            if type(images) is not list or len({i['name'] for i in images})!=len(images) or any(i['name'] not in ('profile.json','definition.json','seasons.json','packs.json','football.json') for i in images):raise ValueError('Invalid recovery image targets')
            if prepared['state_after']['account_id']!=value['account_id'] or prepared['state_after']['account_identity']!=value['account_identity']:raise ValueError('Recovery owner mismatch')
            self._validate_intent(value,prepared)
            self._validate_rewards(prepared['state_after'])
            validate_season_coins(prepared['state_after'])
            validate_title_packs(prepared['state_after'])
            new_matches=prepared['state_after']['matches'][len(value['matches']):]
            reward=new_matches[-1].get('reward') if new_matches else None
            progression=new_matches[-1].get('progression') if new_matches else None
            if reward and not new_matches[-1].get('atomic_match'):
                final=prepared['state_after'];match=new_matches[-1]
                completion=next((c for c in final['completions'] if c['receipt_id']==match['id']),None)
                targets={'profile.json','definition.json','seasons.json'} if completion else {'profile.json'}
                if {i['name'] for i in images}!=targets:raise ValueError('Reward intent has unrelated account effects')
                image=next(i for i in images if i['name']=='profile.json');old=bytes.fromhex(image['before']);new=bytes.fromhex(image['after'])
                if (digest(old),digest(new))!=(reward['profile_before_sha256'],reward['profile_after_sha256']):raise ValueError('Reward intent/profile hash mismatch')
                expected_profile=json.loads(old);expected_profile['credits']=reward['credits_after']
                if completion:expected_profile['division_offline']=completion['outcome']['proposed_next_division']
                if json.loads(old)['credits']!=reward['credits_before']:raise ValueError('Reward credits before image mismatch')
                if json.loads(new)!=expected_profile:raise ValueError('Reward intent changes unrelated profile fields')
            if progression:
                final=prepared['state_after'];match=new_matches[-1]
                completion=next((c for c in final['completions'] if c['receipt_id']==match['id']),None)
                targets={'profile.json','definition.json','seasons.json'} if completion else {'profile.json'}
                if {i['name'] for i in images}!=targets:raise ValueError('Progression intent has unrelated effects')
                image=next(i for i in images if i['name']=='profile.json')
                old=bytes.fromhex(image['before']);new=bytes.fromhex(image['after'])
                if (digest(old),digest(new))!=(progression['profile_before_sha256'],progression['profile_after_sha256']):raise ValueError('Progression profile checksum mismatch')
                expected_profile=json.loads(old)
                expected_profile.update(credits=progression['credits_after'],revival_total_xp=progression['quote']['after']['total_xp'])
                if completion:expected_profile['division_offline']=completion['outcome']['proposed_next_division']
                if json.loads(new)!=expected_profile:raise ValueError('Progression changes unrelated profile fields')
                if expected_profile['revival_total_xp']-progression['quote']['xp']!=json.loads(old).get('revival_total_xp',0):raise ValueError('Progression XP before image mismatch')
                if json.loads(old)['credits']!=progression['credits_before']:raise ValueError('Progression credits before image mismatch')
                if completion:
                    target=completion['outcome']['proposed_next_division']
                    definition_image=next(i for i in images if i['name']=='definition.json')
                    expected_definition=json.loads(bytes.fromhex(definition_image['before']))
                    expected_definition['division_index']=target
                    if json.loads(bytes.fromhex(definition_image['after']))!=expected_definition:raise ValueError('Progression rollover changes unrelated definition fields')
                    season_image=next(i for i in images if i['name']=='seasons.json')
                    expected_season={'persona_id':value['account_identity']['persona_id'],'current':None}
                    if json.loads(bytes.fromhex(season_image['after']))!=expected_season:raise ValueError('Progression rollover fabricates native state')

        from .season_choice_start import validate_cycle as validate_choice_cycle
        validate_choice_cycle(value)
        from .season_forfeit import validate_legacy_selection
        if 'legacy_forfeit_selection' in value['cycle']:
            validate_legacy_selection(value,self.stores()[0].definition)
        return value
    def _validate_intent(self,before,prepared):
        """A pending intent may append one accepted source, never rewrite history.

        Check the complete transition before recovery writes any projection.
        Committed historical records retain their original schema and bytes.
        """
        final=prepared['state_after'];images=prepared['images']
        from .season_forfeit import validate_intent as validate_forfeit_intent
        if validate_forfeit_intent(before,final,images):
            if set(prepared)!={'transaction_id','images','state_after'}:raise ValueError('Invalid forfeiture recovery envelope')
            uuid.UUID(prepared['transaction_id'])
            from .season_forfeit import definition_reference
            if final['season_forfeitures'][-1]['definition_reference']!=definition_reference(self.stores()[0].definition):
                raise ValueError('Forfeiture recovery definition conflict')
            return
        from .season_forfeit import validate_legacy_intent
        if validate_legacy_intent(before,final,images):
            if set(prepared)!={'transaction_id','images','state_after'}:raise ValueError('Invalid legacy initialization envelope')
            uuid.UUID(prepared['transaction_id'])
            from .season_forfeit import validate_legacy_selection
            validate_legacy_selection(final,self.stores()[0].definition)
            return
        from .native_match_forfeit import validate_intent as validate_match_forfeit_intent
        if validate_match_forfeit_intent(self,before,final,images):
            if set(prepared)!={'transaction_id','images','state_after'}:raise ValueError('Invalid match forfeiture envelope')
            uuid.UUID(prepared['transaction_id'])
            return
        if (set(prepared)!={'transaction_id','images','state_after'} or
            (set(final)!=set(before) and not (set(final)==set(before)|{'season_coin_rewards'} and final['season_coin_rewards']==[] and before['active_match'] is None and (final.get('active_match') or {}).get('season_coin_start') is not None)
             and not (set(final)==set(before)|{'season_coin_rewards','aborted_matches'} and
                      final['season_coin_rewards']==[] and final['aborted_matches']==[] and before['active_match'] is None and
                      (final.get('active_match') or {}).get('season_coin_start') is not None and (final.get('active_match') or {}).get('atomic_match'))
             and not (set(final)==set(before)|{'season_definition_history'} and before['active_match'] is None
                      and before['cycle']['status']=='awaiting_native_initialization'
                      and final['cycle'].get('season_choice_selection') is not None)
             and not (set(final)==set(before)|{'season_definition_history'} and
                      (before.get('active_match') or {}).get('atomic_match') and final['active_match'] is None
                      and 'pending_competition_selection' in final['cycle'])
             and not (set(final)==set(before)|{'aborted_matches'} and
                      ((final['aborted_matches']==[] and before['active_match'] is None and (final.get('active_match') or {}).get('atomic_match')) or
                       (len(final['aborted_matches'])==1 and (before.get('active_match') or {}).get('atomic_match') and final['active_match'] is None)))) or final['prepared'] is not None or
            any(final[k]!=before[k] for k in ('schema','account_id','account_identity','policy_version'))):
            raise ValueError('Invalid recovery state transition')
        uuid.UUID(prepared['transaction_id'])
        for key in ('matches','completions'):
            if (type(final[key]) is not list or
                final[key][:len(before[key])]!=before[key] or
                len(final[key])-len(before[key]) not in (0,1)):
                raise ValueError('Recovery cannot rewrite receipt history')
        old_aborted=before.get('aborted_matches',[]);new_aborted=final.get('aborted_matches',[])
        if type(new_aborted) is not list or new_aborted[:len(old_aborted)]!=old_aborted or len(new_aborted)-len(old_aborted) not in (0,1):
            raise ValueError('Recovery cannot rewrite aborted source history')
        from .season_choice_start import validate_intent as validate_choice_intent
        if validate_choice_intent(before,final,images):return
        from .native_atomic_match import validate_intent as validate_atomic_intent
        if validate_atomic_intent(self,before,final,images):return
        if final.get('season_definition_history')!=before.get('season_definition_history'):
            raise ValueError('Only a verified competition selection/final handoff may archive cycle definitions')
        old_rewards=before.get('season_coin_rewards',[]);new_rewards=final.get('season_coin_rewards',[])
        if new_rewards!=old_rewards:
            from .native_season_coin_rewards import validate_reward_intent
            validate_reward_intent(before,final,images);return
        added=final['matches'][len(before['matches']):]
        completed=final['completions'][len(before['completions']):]
        if old_aborted!=new_aborted:raise ValueError('Aborted source requires explicit atomic cancellation')
        from .native_match_xp import validate_intent as validate_xp_intent
        if validate_xp_intent(before,final,images):return
        if not added:
            if images or completed:raise ValueError('Projection changes require an accepted source receipt')
            active=before['active_match'];next_active=final['active_match']
            if final['cycle']!=before['cycle']:
                expected=copy.deepcopy(before['cycle'])
                expected.update(status='active',initial_native_anchor=final['cycle'].get('initial_native_anchor'))
                anchor=expected['initial_native_anchor']
                if (active is not None or next_active is not None or before['cycle']['status']!='awaiting_native_initialization' or
                    final['cycle']!=expected or not anchor or anchor.get('round_number')!=1 or
                    anchor.get('user_points')!=0 or anchor.get('division_index')!=before['cycle']['division']):
                    raise ValueError('Invalid native initialization intent')
            elif active is None:
                if (not next_active or set(next_active)-{'progression_start','pack_entitlement_policy_version','coin_reward_start','fixture_pack_delivery','native_pack_start','season_coin_start','championship_pack_start','native_xp_start','difficulty_reward_start','atomic_match','atomic_pack','played_match','division_season_identity','season_completion_timing','season_choice_handoff','training_effects','injury_effects','level_reward_start'}!=
                    {'id','cycle_id','fixture','status','create_body_hex','policy_version'} or
                    next_active['cycle_id']!=before['cycle']['id'] or next_active['status']!='created' or
                    next_active['policy_version']!=before['policy_version']):raise ValueError('Invalid accepted create intent')
                from .native_played_protocol import validate_source
                validate_source(next_active)
                if next_active.get('training_effects') is not None:raise ValueError('Training must bind at accepted Play, not squad preparation')
                if next_active.get('injury_effects') is not None:raise ValueError('Injury policy must bind at accepted Play')
                if (bool(next_active.get('played_match')) and not (self.native_played_matches or self.native_mixed_matches)) or (self.native_played_matches and not next_active.get('played_match')):raise ValueError('Create mode differs from configured played selector')
                uuid.UUID(next_active['id'])
                if 'atomic_match' in next_active:
                    from .season_choice_reference import snapshot as competition_snapshot
                    expected_reference=competition_snapshot(self.stores()[0].definition)
                    if next_active['atomic_match'].get('competition_reference')!=expected_reference:
                        raise ValueError('Create competition reference differs from live definition')
                    if bool(next_active.get('season_completion_timing'))!=self.native_early_season_completion:
                        raise ValueError('Early completion differs from accepted selector')
                    from .season_completion_timing import validate_source as validate_timing
                    validate_timing(next_active)
                    if bool(next_active.get('atomic_pack'))!=bool(self.atomic_pack_policy):raise ValueError('Atomic pack start selector differs')
                    from .native_atomic_match import require_unchanged
                    require_unchanged(self,next_active)
                    from .native_atomic_match import validate_pack_start
                    validate_pack_start(self,next_active)
                if 'division_season_identity' in next_active:
                    from .native_division_season_identity import snapshot
                    season,_=self.stores()
                    if not next_active.get('atomic_match') or next_active['division_season_identity']!=snapshot(season.load(),before):
                        raise ValueError('Distinct season identity differs from accepted source')
                if 'championship_pack_start' in next_active:
                    from .native_championship_packs import snapshot as title_snapshot
                    if next_active['championship_pack_start']!=title_snapshot(before['cycle']['division'],next_active['championship_pack_start']['definition']):raise ValueError('Wrong prospective championship definition')
                if 'season_coin_start' in next_active:
                    from .native_season_coin_rewards import validate_snapshot
                    if validate_snapshot(next_active['season_coin_start'])['division']!=before['cycle']['division']:raise ValueError('Wrong prospective season reward division')
            else:
                expected=copy.deepcopy(active)
                expected.update(status='playing',play_body_hex=next_active.get('play_body_hex') if next_active else None)
                from .training_expiry import KEY as TRAINING,substitution as training_substitution,validate_source as validate_training
                if next_active and active['status']=='created' and active.get('atomic_match'):
                    from .training_expiry import snapshot as training_snapshot
                    planned=training_snapshot(self.stores()[1])
                    if planned is not None:expected[TRAINING]=planned
                    from .injury_effects import snapshot as injury_snapshot,KEY as INJURY
                    injury=injury_snapshot(self.stores()[1])
                    if injury is not None:expected[INJURY]=injury
                elif next_active and TRAINING in active:
                    old_subs=active[TRAINING]['substitutions'];new_subs=next_active.get(TRAINING,{}).get('substitutions',[])
                    if new_subs!=old_subs:
                        if (active['status']!='playing' or next_active.get('play_body_hex')!=active.get('play_body_hex') or
                                len(new_subs)!=len(old_subs)+1 or new_subs[:-1]!=old_subs):raise ValueError('Invalid trained-player substitution intent')
                        training_substitution(expected,bytes.fromhex(new_subs[-1]))
                    validate_training(expected)
                if not next_active or next_active!=expected or active['status'] not in ('created','playing'):
                    raise ValueError('Invalid accepted play intent')
            return
        match=added[0];active=before['active_match']
        if (not active or active['status']!='playing' or final['active_match'] is not None or
            any(match.get(k)!=v for k,v in active.items() if k!='status') or
            match['status']!='committed' or match['cycle_id']!=before['cycle']['id']):
            raise ValueError('Recovery receipt differs from accepted source')
        if not completed:
            if final['cycle']!=before['cycle']:raise ValueError('Nonfinal receipt changes cycle')
            if match.get('reward') is None and match.get('progression') is None and images:
                raise ValueError('Neutral fixture cannot change account projections')
            return
        completion=completed[0]
        if (completion['receipt_id']!=match['id'] or completion['cycle_id']!=match['cycle_id'] or
            completion['status']!='committed' or completion['policy_version']!=before['policy_version'] or
            completion['rewards_enabled'] is not False or
            completion.get('pack_entitlement_policy_version')!=match.get('pack_entitlement_policy_version')):
            raise ValueError('Completion source mismatch')
        outcome=self.policy.for_division(before['cycle']['division']).evaluate(match['fixture'],match['points_after'])
        if not outcome['complete'] or completion['outcome']!=outcome:raise ValueError('Completion outcome mismatch')
        cycle=final['cycle'];target=outcome['proposed_next_division']
        if cycle!={'id':completion['next_cycle_id'],'division':target,'season_id':before['cycle']['season_id'],
                   'status':'awaiting_native_initialization','previous_cycle_id':before['cycle']['id'],'initial_native_anchor':None}:
            raise ValueError('Completion next-cycle mismatch')
        if {i['name'] for i in images}!={'profile.json','definition.json','seasons.json'}:
            raise ValueError('Rollover projection targets mismatch')
        # Progression additionally validates its complete coin/XP profile below.
        for image in images:
            old=json.loads(bytes.fromhex(image['before']));new=json.loads(bytes.fromhex(image['after']))
            if image['name']=='profile.json':
                old['division_offline']=target
                if match.get('progression') is not None:
                    old.update(credits=match['progression']['credits_after'],
                               revival_total_xp=match['progression']['quote']['after']['total_xp'])
                if match.get('reward') is not None:old['credits']=match['reward']['credits_after']
            elif image['name']=='definition.json':old['division_index']=target
            else:old={'persona_id':before['account_identity']['persona_id'],'current':None}
            if new!=old:raise ValueError('Rollover changes unrelated account fields')
    def _validate_rewards(self,state):
        from .native_match_xp import validate as validate_xp
        validate_xp(state)
        from .native_atomic_match import validate_staged_source
        validate_staged_source(self,state)
        from .local_profile import validate_credits
        from .native_match_reward_policy import response_fields
        active=state['active_match']
        for source in ([active] if active else [])+state['matches']:
            # validate_staged_source above already validates each forfeit.
            if source.get('native_match_forfeit') and source['status']=='committed':continue
            from .difficulty_rewards import validate_source as validate_difficulty_source
            validate_difficulty_source(source)
            if source.get('native_pack_start') is not None:
                from .native_match_pack_policy import validate_snapshot
                snap=validate_snapshot(source['native_pack_start'])
                if source.get('pack_entitlement_policy_version')!='backend_pack_entitlement_test_v1':raise ValueError('Invalid native pack source')
                request=json.loads(bytes.fromhex(source['create_body_hex']))
                if request['divisionId']!=11-snap['division']:raise ValueError('Pack snapshot differs from accepted source division')
                if source.get('status')=='committed':
                    pick=snap['outcomes'][source['result']]
                    expected={'definition':pick['definition'],'definition_sha256':pick['definition_sha256'],'classification':'isolated_transport_test'}
                    if source.get('fixture_pack_delivery')!=expected:raise ValueError('Pack delivery differs from genuine result')
            delivery=source.get('fixture_pack_delivery')
            if delivery is not None:
                from .local_packs import DEFINITIONS
                if (source.get('pack_entitlement_policy_version')!='backend_pack_entitlement_test_v1' or
                    type(delivery) is not dict or set(delivery)!={'definition','definition_sha256','classification'} or
                    delivery['classification']!='isolated_transport_test' or type(delivery['definition']) is not str or delivery['definition'] not in DEFINITIONS or
                    delivery['definition_sha256']!=digest(encode(DEFINITIONS[delivery['definition']]))):
                    raise ValueError('Invalid pinned fixture pack delivery')
        if active and active.get('coin_reward_start') is not None:
            self._validate_coin_start(active['coin_reward_start'],state['cycle']['division'])
        if active and ('pack_entitlement_policy_version' in active and
                       active['pack_entitlement_policy_version']!='backend_pack_entitlement_test_v1'):
            raise ValueError('Invalid accepted pack source policy')
        if active and active.get('progression_start') is not None:
            from .account_progression import level_state
            snapshot=active['progression_start']
            if (type(snapshot) is not dict or set(snapshot)!={'total_xp','level','division','policy_version'} or
                snapshot['policy_version']!='account_progression_v1' or snapshot['division']!=state['cycle']['division'] or
                type(snapshot['division']) is not int or type(snapshot['level']) is not int or
                snapshot['level']!=level_state(snapshot['total_xp'])['level']):raise ValueError('Invalid active start snapshot')
        pairs=[(m['cycle_id'],m['fixture']) for m in state['matches']]
        if len(set(pairs))!=len(pairs):raise ValueError('Fixture consumed twice in same cycle')
        for completion in state['completions']:
            if 'pack_entitlement_policy_version' in completion:
                source=next((m for m in state['matches'] if m['id']==completion['receipt_id']),None)
                if (source is None or source['cycle_id']!=completion['cycle_id'] or
                    completion['pack_entitlement_policy_version']!='backend_pack_entitlement_test_v1' or
                    source.get('pack_entitlement_policy_version')!=completion['pack_entitlement_policy_version']):
                    raise ValueError('Invalid season pack source policy')
        for match in state['matches']:
            if match.get('native_match_forfeit'):continue
            if ('pack_entitlement_policy_version' in match and
                match['pack_entitlement_policy_version']!='backend_pack_entitlement_test_v1'):
                raise ValueError('Invalid source entitlement policy')
            amount=match['reward_coins'];reward=match.get('reward')
            if match.get('progression') is not None:
                self._validate_progression(state,match)
                continue
            if reward and reward.get('policy_version') in ('native_match_coins_v1','difficulty_rewards_v1'):
                self._validate_coin_reward(state,match)
                continue
            if match.get('coin_reward_start') is not None:raise ValueError('Accepted coin source cannot lose its reward')
            if type(amount) is not int or not 0<=amount<=100 or match['reward_xp']!=(match.get('native_xp_report') or {}).get('quote',{}).get('xp',0):raise ValueError('Invalid native test reward amount')
            if amount==0:
                if reward is not None:raise ValueError('Unexpected zero reward record')
                continue
            if (type(reward) is not dict or reward['amount']!=amount or reward['policy_version']!='native_match_reward_test_v1' or
                reward['classification']!='revival_policy_test_only' or reward['status']!='committed' or
                reward['source_receipt_id']!=match['id'] or reward['cycle_id']!=match['cycle_id'] or
                reward['fixture_index']!=match['fixture'] or reward['account_id']!=state['account_id'] or
                reward['persona_id']!=state['account_identity']['persona_id'] or
                reward['id']!=str(uuid.uuid5(uuid.UUID(match['id']),'native-match-coins')) or
                reward['credits_after']!=validate_credits(reward['credits_before']+amount) or
                match['response']!=response_fields(amount) or match['fixture']>=10):raise ValueError('Reward receipt/source/persistence mismatch')
            for key in ('profile_before_sha256','profile_after_sha256'):
                if len(reward[key])!=64 or any(c not in '0123456789abcdef' for c in reward[key]):raise ValueError('Invalid reward profile checksum')

    def _validate_coin_start(self,snapshot,division):
        from .account_progression import level_state
        if (type(snapshot) is not dict or set(snapshot)!={'total_xp','level','division','policy_version'} or
            snapshot['policy_version'] not in ('native_match_coins_v1','difficulty_rewards_v1') or type(snapshot['division']) is not int or
            snapshot['division']!=division or type(snapshot['level']) is not int or
            snapshot['level']!=level_state(snapshot['total_xp'])['level']):raise ValueError('Invalid accepted coin-start snapshot')

    def _validate_coin_reward(self,state,match):
        from .revival_rewards import match_coin_quote
        from .local_profile import validate_credits
        from .native_match_reward_policy import response_fields
        snapshot=match.get('coin_reward_start')
        if not snapshot:raise ValueError('Missing accepted match coin snapshot')
        self._validate_coin_start(snapshot,snapshot['division'])
        from .difficulty_rewards import source_coin_quote
        expected=source_coin_quote(match,match['result'])
        reward=match['reward'];amount=expected['amount']
        reply=response_fields(amount)
        from .season_completion_timing import source_outcome
        outcome=source_outcome(match,snapshot['division'],match['points_after'],season_policy=self.policy)
        if match.get('season_coin_start') is not None:
            from .native_season_coin_rewards import awards_response
            reply=awards_response(match['season_coin_start'],outcome,amount)
        if outcome['complete']:reply['seasonEndResult']=outcome['preview_band']
        validate_credits(reward['credits_before'])
        if (reward['policy_version']!=snapshot['policy_version'] or reward['quote']!=expected or reward['classification']!='revival_policy' or
            reward['amount']!=amount or type(match['reward_coins']) is not int or match['reward_coins']!=amount or
            type(match['reward_xp']) is not int or match['reward_xp']!=(match.get('native_xp_report') or {}).get('quote',{}).get('xp',0) or match.get('progression') is not None or
            reward['status']!='committed' or reward['source_receipt_id']!=match['id'] or
            reward['cycle_id']!=match['cycle_id'] or reward['fixture_index']!=match['fixture'] or
            reward['account_id']!=state['account_id'] or reward['persona_id']!=state['account_identity']['persona_id'] or
            reward['id']!=str(uuid.uuid5(uuid.UUID(match['id']),'native-match-coins')) or
            reward['credits_after']!=validate_credits(reward['credits_before']+amount) or match['response']!=reply):
            raise ValueError('Approved match coin receipt/source/policy mismatch')
        for key in ('profile_before_sha256','profile_after_sha256'):
            if len(reward[key])!=64 or any(c not in '0123456789abcdef' for c in reward[key]):raise ValueError('Invalid coin profile checksum')

    def _validate_progression(self,state,match):
        from .account_progression import quote,load_progression_policy
        from .local_profile import validate_credits
        p=match['progression'];snapshot=match.get('progression_start')
        if type(snapshot) is not dict:raise ValueError('Missing accepted match-start XP snapshot')
        if set(snapshot)!={'total_xp','level','division','policy_version'} or snapshot['policy_version']!='account_progression_v1':raise ValueError('Invalid start policy snapshot')
        expected=quote(load_progression_policy(),snapshot['division'],match['result'],snapshot['total_xp'])
        validate_credits(p['credits_before'])
        if (p['quote']!=expected or type(snapshot['level']) is not int or snapshot['level']!=expected['start']['level'] or
            p['source_receipt_id']!=match['id'] or p['account_id']!=state['account_id'] or
            p['persona_id']!=state['account_identity']['persona_id'] or p['cycle_id']!=match['cycle_id'] or
            p['fixture_index']!=match['fixture'] or p['status']!='committed' or
            p['certification']!='backend_only' or p['id']!=str(uuid.uuid5(uuid.UUID(match['id']),'account-progression')) or
            match['reward_coins']!=expected['coins'] or match['reward_xp']!=expected['xp'] or
            p['credits_after']!=validate_credits(p['credits_before']+expected['coins']) or match.get('reward') is not None):
            raise ValueError('Progression receipt/source/policy mismatch')
        # No positive native XP or coin response is produced in backend-only mode.
        if set(match['response'])-{'seasonEndResult'}:raise ValueError('Backend progression cannot install stock awards')
        for key in ('profile_before_sha256','profile_after_sha256'):
            if len(p[key])!=64 or any(c not in '0123456789abcdef' for c in p[key]):raise ValueError('Invalid progression checksum')

    def identity(self):
        p=load_profile(self.account/'profile.json')
        return {'persona_id':p.persona_id,'identity_pid':p.identity_pid,'user_id':p.user_id}
    def initialize(self):
        with self.locked():
            if self.path.exists():return self._recover(self._load())
            season,_=self.stores();current=season.load()
            if current is None:raise ValueError('Original season anchor required')
            profile=load_profile(self.account/'profile.json')
            if profile.division_offline!=current.division_index:raise ValueError('Profile/season mismatch')
            from .first_run_account import account_id as setup_account_id
            owner = setup_account_id(self.account) or str(uuid.uuid4())
            state={'schema':1,'account_id':owner,'account_identity':self.identity(),
                   'policy_version':self.policy.version,'cycle':{'id':str(uuid.uuid4()),'division':current.division_index,
                   'season_id':current.season_id,'status':'active','initial_native_anchor':asdict(current)},
                   'active_match':None,'matches':[],'completions':[],'prepared':None}
            if self.backend_season_coin_rewards:state['season_coin_rewards']=[]
            atomic(self.path,encode(state));return state
    def _recover(self,state):
        prepared=state['prepared']
        if prepared is None:return self._recover_reward_deliveries(state)
        # Preflight every file before the first write. A late-file conflict must
        # not advance earlier projections while refusing the transaction.
        recover_images(self.account,prepared['images'],writer=atomic,fault=self.fault)
        final=prepared['state_after'];final['prepared']=None
        atomic(self.path,encode(final))
        if self.fault:self.fault('after_source_commit',0)
        return self._recover_reward_deliveries(final)

    def _recover_reward_deliveries(self,state):
        from .native_season_coin_rewards import recover as recover_season_coins
        return self._recover_pack_deliveries(recover_season_coins(self,state))

    def _recover_pack_deliveries(self,state):
        """Recover separate entitlement transactions from prospective source intent.

        The committed native source is the durable pending identity. PackStore
        atomically records its stable reward ID with unopened ownership; a lost
        acknowledgement or consumed-pack retry cannot allocate another pack.
        Caller already holds native -> packs -> profile locks, never reenter them.
        No legacy receipt without a CreateSim delivery snapshot is eligible.
        """
        from .native_atomic_match import validate_pack_ownership
        validate_pack_ownership(self,state)
        for source in state['matches']:
            delivery=source.get('fixture_pack_delivery')
            if delivery is not None:
                self._grant_pack_locked(state,source['id'],delivery['definition'],'fixture')
        for source in state['completions']:
            delivery=source.get('season_pack_delivery')
            if delivery is not None:self._grant_pack_locked(state,source['id'],delivery['definition'],'season')
        return state
    def recover(self):
        with self.locked():return self._recover(self._load())
    def grant_pack_for_source(self,source_id,definition,*,source_kind='fixture'):
        """Explicit isolated backend test grant; no route/default activates it.

        Definition is a supported test resource, not an alias for an unproved
        approved Bronze/Silver/mixed product. Automatic reward binding is separate.
        Source and entitlement commit in one existing PackStore atomic image.
        """
        if not self.backend_pack_entitlements:raise ValueError('Backend source entitlements disabled')
        if source_kind not in ('fixture','season'):raise ValueError('Invalid pack source kind')
        with self.locked():
            state=self._recover(self._load())
            return self._grant_pack_locked(state,source_id,definition,source_kind)

    def _grant_pack_locked(self,state,source_id,definition,source_kind):
        collection=state['matches'] if source_kind=='fixture' else state['completions']
        source=next((r for r in collection if r['id']==source_id),None)
        if source is None or source['status']!='committed':raise ValueError('Committed account source receipt required')
        if source.get('pack_entitlement_policy_version')!='backend_pack_entitlement_test_v1':
            raise ValueError('No retroactive source pack grant; opt in before match creation')
        delivery=source.get('fixture_pack_delivery' if source_kind=='fixture' else 'season_pack_delivery')
        if delivery is not None and delivery['definition']!=definition:raise ValueError('Pack definition differs from accepted delivery')
        receipt={'reward_id':str(uuid.uuid5(uuid.UUID(source_id),source_kind+'-pack')),
                 'source_id':source_id,'source_kind':source_kind,'account_id':state['account_id'],
                 'persona_id':state['account_identity']['persona_id'],'cycle_id':source['cycle_id'],
                 'policy_version':'backend_pack_entitlement_test_v1','certification':'backend_only'}
        from .local_packs import PackStore
        packs=PackStore(self.account/'packs.json');existing=packs.load().get('source_grants',[])
        for record in existing:
            sources=state['matches'] if record['source_kind']=='fixture' else state['completions']
            owner=next((r for r in sources if r['id']==record['source_id']),None)
            if (record['account_id']!=state['account_id'] or record['persona_id']!=state['account_identity']['persona_id'] or
                owner is None or owner['status']!='committed' or owner['cycle_id']!=record['cycle_id'] or
                owner.get('pack_entitlement_policy_version')!='backend_pack_entitlement_test_v1'):
                raise ValueError('Foreign or conflicting pack reward source owner')
        return packs._grant_from_source(definition,receipt,state['account_identity']['persona_id'])
    def _transaction(self,before,after,images):
        intent=copy.deepcopy(before)
        intent['prepared']={'transaction_id':str(uuid.uuid4()),'images':images,'state_after':after}
        self._validate_intent(before,intent['prepared'])
        atomic(self.path,encode(intent))
        if self.fault:self.fault('after_intent',0)
        return self._recover(intent)
    def _image(self,name,after):
        path=self.account/name
        return {'name':name,'before':path.read_bytes().hex(),'after':after.hex()}
    def _anchor(self,state):
        season,football=self.stores();current=season.load()
        cycle=state['cycle']
        if cycle['status']!='active' or current is None:raise ValueError('New native season initialization required')
        if (current.season_id,current.division_index)!=(cycle['season_id'],cycle['division']):raise ValueError('Cycle differs from original season')
        previous=next((m for m in reversed(state['matches']) if m['cycle_id']==cycle['id']),None)
        if previous and current.round_number<=previous['fixture']:raise ValueError('Original native save still pending')
        if previous and (current.round_number,current.user_points)!=(previous['fixture']+1,previous['points_after']):raise ValueError('Native save differs from accepted result')
        return season,football,current
    def played_report_end_source(self,state):
        """Current authenticated report is the identity, regardless of End bytes.

        Called under the journal lock on validated state. This same resolver
        handles ordinary and equal-body played completions; no history hash is
        used to decide whether the current completed source exists.
        """
        source=state['active_match']
        if (not self.backend_played_report_bound_end_identity or not self.native_match_xp or
                not source or not source.get('played_match') or source['status']!='playing' or
                not source.get('native_xp_report')):
            return None
        return source
    def _proposal(self,state,method,target,headers,body):
        # Keep the certified identity/framing resolver unchanged. Only an
        # accepted prospective atomic source may change its completion timing.
        proposal=self._preview(state,method,target,headers,body)
        source=state['active_match']
        if proposal and proposal['operation']=='end' and source and source.get('season_completion_timing'):
            from .native_atomic_match import pure_end_proposal
            return pure_end_proposal(self,state,source,body)
        return proposal
    def _preview(self,state,method,target,headers,body):
        difficulty_mode=self.difficulty_mode(state)
        from . import native_played_protocol, native_simulation_protocol
        played=self.native_played_matches
        if self.native_mixed_matches:
            if target in (native_played_protocol.CREATE_PATH,native_played_protocol.END_PATH):played=True
            elif target in (native_simulation_protocol.CREATE_PATH,native_simulation_protocol.END_PATH):played=False
            else:return None
        mode=native_played_protocol if played else native_simulation_protocol
        CREATE_PATH,END_PATH=mode.CREATE_PATH,mode.END_PATH
        inspect_create,inspect_end,play_ack=mode.inspect_create,mode.inspect_end,mode.play_ack
        active=state['active_match']
        if active and bool(active.get('played_match'))!=played:
            raise ValueError('Cannot change played/Sim mode during fixture')
        if active and bool(active.get('difficulty_reward_start'))!=difficulty_mode:
            raise ValueError('Cannot change difficulty rewards during accepted fixture')
        if active and bool(active.get('atomic_pack'))!=bool(self.atomic_pack_policy):
            raise ValueError('Cannot change atomic pack mode during accepted match')
        if active and bool(active.get('atomic_match'))!=self.native_atomic_matches:
            raise ValueError('Cannot change atomic match policy during fixture')
        if self.native_atomic_matches and active:
            from .native_atomic_match import require_unchanged
            require_unchanged(self,active)
            if target==END_PATH and active.get('atomic_end'):
                from .native_atomic_match import valid_save_owner
                if not valid_save_owner(method,headers,body) or body.hex()!=active['atomic_end']['body_hex']:
                    raise ValueError('Conflicting staged End retry')
                return dict(active['atomic_end']['proposal'],operation='atomic_end_retry')
            if target==CREATE_PATH and active.get('native_xp_report'):
                raise ValueError('Completed atomic fixture cannot be replayed')
        if active and (active.get('championship_pack_start',{}).get('definition')!=self.championship_pack_definition):raise ValueError('Cannot change title pack policy during accepted match')
        if active and bool(active.get('season_coin_start'))!=self.backend_season_coin_rewards:raise ValueError('Cannot change season coin policy during accepted match')
        if active and active.get('native_pack_start')!=self._pack_snapshot(state['cycle']['division']):raise ValueError('Cannot change match pack policy during accepted match')
        if target not in (CREATE_PATH,END_PATH):return None
        if method=='POST' and target==CREATE_PATH:
            season,football,current=self._anchor(state)
            for previous in state['matches']:
                if previous['cycle_id']==state['cycle']['id'] and bool(previous.get('difficulty_reward_start'))!=difficulty_mode:
                    raise ValueError('Difficulty rewards may change only before a fresh season begins')
            observed=inspect_create(method,target,headers,body,season,football)
            if difficulty_mode:
                from .difficulty_rewards import snapshot as difficulty_snapshot
                difficulty_snapshot(season.definition,current.round_number,load_profile(self.account/'profile.json').revival_total_xp or 0)
            if self.atomic_pack_policy:
                from .native_match_pack_policy import snapshot
                snapshot(current.division_index,self.atomic_pack_policy)
                self._check_pack_capacity(1)
            if self.championship_pack_definition is not None:
                from .native_championship_packs import snapshot as title_snapshot
                planned_title=title_snapshot(current.division_index,self.championship_pack_definition)
                if active and active.get('championship_pack_start')!=planned_title:raise ValueError('Accepted title pack snapshot changed')
            if self.backend_season_coin_rewards:
                from .native_season_coin_rewards import snapshot as season_snapshot
                if difficulty_mode:
                    from .native_season_coin_rewards import difficulty_snapshot
                    planned_season=difficulty_snapshot(season.definition,awards_projection=self.backend_season_awards_projection,season_prize_display=self.backend_season_prize_display)
                else:
                    planned_season=season_snapshot(current.division_index,awards_projection=self.backend_season_awards_projection,season_prize_display=self.backend_season_prize_display)
                if active and active.get('season_coin_start')!=planned_season:raise ValueError('Accepted season coin snapshot changed')
            active=state['active_match']
            if active and active.get('fixture_pack_delivery')!=self.fixture_pack_delivery:raise ValueError('Cannot change fixture pack delivery during accepted match')
            if self.has_match_pack_policy:
                planned=self._pack_snapshot(current.division_index)
                if active and active.get('native_pack_start')!=planned:raise ValueError('Native pack source snapshot changed')
            possible_title=(self.championship_pack_definition is not None and current.round_number==10 and
                            self.policy.for_division(current.division_index).evaluate(10,current.user_points+3)['preview_band']=='CHAMPIONSHIP')
            self._check_pack_capacity(int(self.has_match_pack_policy or self.fixture_pack_delivery is not None)+int(possible_title))
            if active and (active['fixture']!=current.round_number or active['create_body_hex']!=body.hex()):raise ValueError('One accepted match per cycle fixture; abandonment needs explicit audit')
            if active and bool(active.get('native_xp_start'))!=self.native_match_xp:raise ValueError('Cannot change native XP mode during fixture')
            if active and bool(active.get('progression_start'))!=bool(self.progression_policy):raise ValueError('Cannot change progression policy during accepted match')
            if active and bool(active.get('coin_reward_start'))!=self.coin_rewards:raise ValueError('Cannot change match coin policy during accepted match')
            if self.coin_rewards:
                from .native_match_reward_policy import reward_marker
                reward_marker(self.account,state,current,self.reward_policy)
            if active and bool(active.get('pack_entitlement_policy_version'))!=self.backend_pack_entitlements:
                raise ValueError('Cannot change pack source policy during accepted match')
            response={}
            if played:
                import time
                response=active['played_match']['create_response'] if active else {'startDateTime':int(time.time())}
            return {'operation':'create','observation':observed,'response':response}
        if method=='PUT' and target==CREATE_PATH:
            active=state['active_match']
            if not active or active['status'] not in ('created','playing'):raise ValueError('No accepted CreateSim')
            if bool(active.get('native_xp_start'))!=self.native_match_xp:raise ValueError('Cannot change native XP mode during fixture')
            if active.get('fixture_pack_delivery')!=self.fixture_pack_delivery:raise ValueError('Cannot change fixture pack delivery during accepted match')
            if bool(active.get('coin_reward_start'))!=self.coin_rewards:raise ValueError('Cannot change match coin policy during accepted match')
            season,football,current=self._anchor(state)
            if (played and active['status']=='playing' and active.get('play_body_hex')
                    and active['play_body_hex']!=body.hex()):
                from .play_game import response_for as substitution_ack
                if (active['fixture']!=current.round_number or
                    substitution_ack(method,target,headers,body,football,allow_substitutions=True) is None):
                    raise ValueError('Wrong substitution membership/framing')
                return {'operation':'substitution','response':{}}
            if active['fixture']!=current.round_number or play_ack(method,target,headers,body,football,enabled=True) is None:raise ValueError('Wrong PlaySim membership/fixture')
            if played and len(json.loads(body)['items'])==1:
                raise ValueError('Substitution requires the accepted initial roster')
            if active.get('play_body_hex') not in (None,body.hex()):raise ValueError('Conflicting PlaySim retry')
            return {'operation':'play','response':{}}
        if method=='PUT' and target==END_PATH:
            # A completed receipt is returned only while no subsequent match is
            # active. Repeated bodies are never treated as a new match identity.
            source=self.played_report_end_source(state) if played else None
            prior=None if source else next((m for m in reversed(state['matches']) if m['end_body_hex']==body.hex() and bool(m.get('played_match'))==played),None)
            if prior:
                if state['active_match'] is None:
                    if headers.get(b'host')!=b'10.0.2.2:18081' or headers.get(b'x-ut-sid')!=b'fifa16-local-sid' or headers.get(b'content-length')!=str(len(body)).encode() or headers.get(b'content-type')!=b'application/json':raise ValueError('Wrong completion retry framing/owner')
                    return {'operation':'end_retry','response':prior['response'],'receipt':prior}
                # RS4 End has no fixture ID. A separately authenticated genuine
                # GameReport now provides one: current source/session + normal
                # completion + score. Without it the historical refusal stays.
                # The normal inspect_end/report agreement checks below still
                # apply; a repeated body alone never authorizes another grant.
                report_bound=(self.backend_played_report_bound_end_identity if played else self.backend_report_bound_end_identity)
                if not report_bound or not self.native_match_xp or not state['active_match'].get('native_xp_report'):
                    raise ValueError('Ambiguous stale/new completion; cannot associate identical body')
            active=state['active_match']
            if not active or active['status']!='playing':raise ValueError('Completion has no accepted playing lifecycle')
            if active.get('fixture_pack_delivery')!=self.fixture_pack_delivery:raise ValueError('Cannot change fixture pack delivery during accepted match')
            season,football,current=self._anchor(state)
            if active['cycle_id']!=state['cycle']['id'] or active['fixture']!=current.round_number:raise ValueError('Completion cycle/fixture mismatch')
            observation=inspect_end(method,target,headers,body,season,football)
            from .injury_effects import validate_end as validate_injury_end
            validate_injury_end(active,body)
            outcome=self.policy.for_division(current.division_index).evaluate(observation['expected_round']-1,observation['expected_points'])
            fixture_pack=active.get('native_pack_start') is not None or active.get('fixture_pack_delivery') is not None
            title_pack=outcome['complete'] and outcome['preview_band']=='CHAMPIONSHIP' and active.get('championship_pack_start') is not None
            # Caller holds the pack lock through source and reward commits.
            # Refuse before wallet/standings/rollover images when either promised
            # entitlement cannot fit; coin-only operation has no pack dependency.
            self._check_pack_capacity(int(fixture_pack)+int(title_pack))
            response={'seasonEndResult':outcome['preview_band']} if outcome['complete'] else {}
            reward=None
            progression=None
            if bool(active.get('coin_reward_start'))!=self.coin_rewards:raise ValueError('Cannot change match coin policy during accepted match')
            if bool(active.get('native_xp_start'))!=self.native_match_xp:raise ValueError('Cannot change native XP mode during fixture')
            if self.native_match_xp:
                report=active.get('native_xp_report')
                if not report or report['observation']['score']!=observation['score'] or report['observation']['result']!=observation['result']:raise ValueError('Native End lacks matching original XP report')
            if bool(active.get('progression_start'))!=bool(self.progression_policy):raise ValueError('Cannot change progression policy during accepted match')
            if bool(active.get('pack_entitlement_policy_version'))!=self.backend_pack_entitlements:
                raise ValueError('Cannot change pack source policy during accepted match')
            if self.progression_policy is not None:
                from .account_progression import quote
                from .local_profile import validate_credits
                profile=load_profile(self.account/'profile.json');snapshot=active['progression_start']
                if snapshot['division']!=current.division_index or snapshot['policy_version']!=self.progression_policy['version']:raise ValueError('Start snapshot division/policy mismatch')
                if (profile.revival_total_xp or 0)!=snapshot['total_xp']:raise ValueError('XP changed during active match; explicit reconciliation required')
                calculation=quote(self.progression_policy,snapshot['division'],observation['result'],snapshot['total_xp'])
                progression={'quote':calculation,'credits_before':profile.credits,
                    'credits_after':validate_credits(profile.credits+calculation['coins']),
                    'profile_before_sha256':digest((self.account/'profile.json').read_bytes())}
            if self.reward_policy is not None:
                from .native_match_reward_policy import reward_quote,response_fields
                reward=reward_quote(self.account,state,current,self.reward_policy,observation['result'])
                response.update(response_fields(reward['amount']))
            if active.get('season_coin_start') is not None and outcome['complete']:
                from .native_season_coin_rewards import quote as season_coin_quote
                bonus=season_coin_quote(active['season_coin_start'],outcome['preview_band'])
                from .local_profile import validate_credits
                projected=load_profile(self.account/'profile.json').credits
                if reward is not None:projected=reward['credits_after']
                if progression is not None:projected=progression['credits_after']
                validate_credits(projected+bonus['amount'])
                if reward is not None:
                    from .native_season_coin_rewards import awards_response
                    response.update(awards_response(active['season_coin_start'],outcome,reward['amount']))
            return {'operation':'end','observation':observation,'outcome':outcome,
                    'response':response,'reward':reward,'progression':progression}
        return None
    def preview(self,method,target,headers,body):
        with self.locked():
            before=self._recover(self._load())
            from .native_match_forfeit import proposal as match_forfeit_proposal
            proposed=match_forfeit_proposal(self,before,method,target,headers,body)
            if proposed is not None:return proposed
            from .season_forfeit import reset_path,proposal as forfeit_proposal
            if reset_path(target) is not None:
                return forfeit_proposal(self,before,method,target,headers,body)
            if self.native_atomic_matches and target.startswith('/ut/game/fifaworldmobile/season/') and method=='PUT':
                from .native_atomic_match import save_proposal
                return save_proposal(self,before,method,target,headers,body)
            if self.native_match_xp:
                from .native_match_xp import preview as xp_preview
                from .native_match_session import REPORT_PATH
                if target==REPORT_PATH:return xp_preview(self,before,method,target,headers,body)
            return self._proposal(before,method,target,headers,body)
    def accept(self,method,target,headers,body):
        with self.locked():
            before=self._recover(self._load())
            from .native_match_forfeit import proposal as match_forfeit_proposal
            proposed=match_forfeit_proposal(self,before,method,target,headers,body)
            if proposed is not None:
                if proposed['operation'] in ('match_forfeit_end','match_forfeit_save','match_forfeit_report_stage','match_forfeit_final'):
                    self._transaction(before,proposed['after'],proposed['images'])
                return proposed
            from .season_forfeit import reset_path,proposal as forfeit_proposal
            if reset_path(target) is not None:
                proposal=forfeit_proposal(self,before,method,target,headers,body)
                if proposal and proposal['operation']=='season_forfeit':
                    self._transaction(before,proposal['after'],proposal['images'])
                return proposal
            from .victory_session import is_authentication
            if self.native_atomic_matches and is_authentication(method,target):
                from .native_atomic_match import abort_for_authentication
                return abort_for_authentication(self,before,method,target,headers,body)
            if self.native_atomic_matches and target.startswith('/ut/game/fifaworldmobile/season/') and method=='PUT':
                from .native_atomic_match import save_proposal,final_state
                proposal=save_proposal(self,before,method,target,headers,body)
                if proposal and proposal['operation']=='atomic_save':
                    after,images=final_state(self,before,proposal)
                    self._transaction(before,after,images)
                elif proposal and proposal['operation']=='atomic_initialization':
                    after=copy.deepcopy(before);after['cycle'].update(status='active',initial_native_anchor=proposal['current'])
                    self._transaction(before,after,[self._image('seasons.json',encode({'persona_id':before['account_identity']['persona_id'],'current':proposal['current']}))])
                return proposal
            if self.native_match_xp:
                from .native_match_xp import preview as xp_preview,accept as xp_accept
                from .native_match_session import REPORT_PATH
                if target==REPORT_PATH:
                    proposal=xp_preview(self,before,method,target,headers,body)
                    return xp_accept(self,before,proposal,body) if proposal is not None else None
            proposal=self._proposal(before,method,target,headers,body)
            if proposal is None:return None
            op=proposal['operation'];after=copy.deepcopy(before);images=[]
            if op=='end_retry':return proposal
            if op=='atomic_end_retry':return proposal
            if op=='substitution':
                from .training_expiry import substitution as training_substitution
                training_substitution(after['active_match'],body)
                if after!=before:self._transaction(before,after,[])
                return proposal
            if op=='create':
                if before['active_match']:return proposal
                observed=proposal['observation']
                after['active_match']={'id':str(uuid.uuid4()),'cycle_id':before['cycle']['id'],'fixture':observed['fixture_index'],
                    'status':'created','create_body_hex':body.hex(),'policy_version':self.policy.version}
                if target=='/ut/game/fifaworldmobile/match':
                    from .native_played_protocol import VERSION as PLAYED_VERSION
                    after['active_match']['played_match']={'version':PLAYED_VERSION,'create_response':proposal['response']}
                if self.native_atomic_matches:
                    from .native_atomic_match import VERSION
                    after.setdefault('aborted_matches',[])
                    after['active_match']['atomic_match']={'version':VERSION,
                        'profile_before_hex':(self.account/'profile.json').read_bytes().hex(),
                        'season_before_hex':(self.account/'seasons.json').read_bytes().hex()}
                    from .season_choice_reference import snapshot as competition_snapshot
                    reference=competition_snapshot(self.stores()[0].definition)
                    if reference is not None:
                        after['active_match']['atomic_match']['competition_reference']=reference
                    if self.atomic_pack_policy:
                        from .native_match_pack_policy import snapshot
                        pack_raw=(self.account/'packs.json').read_bytes()
                        pack_quote=snapshot(before['cycle']['division'],self.atomic_pack_policy)
                        if self.compact_pack_records:
                            from .atomic_pack_reference import snapshot as reference_snapshot
                            after['active_match']['atomic_pack']=reference_snapshot(pack_raw,pack_quote)
                        else:
                            after['active_match']['atomic_pack']={'policy':pack_quote,'packs_before_hex':pack_raw.hex()}
                if self.native_match_xp:
                    from .native_match_xp import snapshot as xp_snapshot
                    after['active_match']['native_xp_start']=xp_snapshot(load_profile(self.account/'profile.json'),before['cycle']['division'])
                    from . import level_rewards
                    from .atomic_pack_reference import VERSION_WIDE
                    pack=after['active_match'].get('atomic_pack') or {}
                    # XP-004: only prospective, wide-identity atomic matches pay level-ups.
                    if level_rewards.enabled(self.account) and pack.get('version')==VERSION_WIDE:
                        after['active_match']['level_reward_start']=level_rewards.start()
                if self.championship_pack_definition is not None:
                    from .native_championship_packs import snapshot as title_snapshot
                    after['active_match']['championship_pack_start']=title_snapshot(before['cycle']['division'],self.championship_pack_definition)
                if self.backend_season_coin_rewards:
                    from .native_season_coin_rewards import snapshot as season_snapshot
                    after.setdefault('season_coin_rewards',[])
                    if self.difficulty_mode(before):
                        from .native_season_coin_rewards import difficulty_snapshot
                        after['active_match']['season_coin_start']=difficulty_snapshot(self.stores()[0].definition,awards_projection=self.backend_season_awards_projection,season_prize_display=self.backend_season_prize_display)
                    else:
                        after['active_match']['season_coin_start']=season_snapshot(before['cycle']['division'],awards_projection=self.backend_season_awards_projection,season_prize_display=self.backend_season_prize_display)
                    if self.atomic_pack_policy:
                        from .native_match_pack_policy import championship_definition
                        from .native_championship_packs import snapshot as title_snapshot
                        definition=championship_definition(before['cycle']['division'],self.atomic_pack_policy)
                        if definition is not None:
                            after['active_match']['atomic_pack']['championship_start']=title_snapshot(before['cycle']['division'],definition)
                if self.backend_pack_entitlements:
                    after['active_match']['pack_entitlement_policy_version']='backend_pack_entitlement_test_v1'
                if self.native_early_season_completion:
                    from .season_completion_timing import snapshot as timing_snapshot
                    after['active_match']['season_completion_timing']=timing_snapshot(before['cycle']['division'])
                if self.fixture_pack_delivery is not None:
                    after['active_match']['fixture_pack_delivery']=copy.deepcopy(self.fixture_pack_delivery)
                if self.has_match_pack_policy:
                    after['active_match']['native_pack_start']=self._pack_snapshot(before['cycle']['division'])
                if self.coin_rewards:
                    from .account_progression import level_state
                    profile=load_profile(self.account/'profile.json');snapshot=level_state(profile.revival_total_xp or 0)
                    after['active_match']['coin_reward_start']={'total_xp':snapshot['total_xp'],'level':snapshot['level'],
                        'division':before['cycle']['division'],'policy_version':self.reward_policy['version']}
                if self.difficulty_mode(before):
                    from .difficulty_rewards import snapshot as difficulty_snapshot,VERSION as DIFFICULTY_VERSION
                    after['active_match']['difficulty_reward_start']=difficulty_snapshot(self.stores()[0].definition,observed['fixture_index'],profile.revival_total_xp or 0)
                    after['active_match']['coin_reward_start']['policy_version']=DIFFICULTY_VERSION
                from .season_choices import ChoiceDefinition
                if self.released_choices and not isinstance(self.stores()[0].definition,ChoiceDefinition):
                    after['active_match']['season_choice_handoff']={'version':'native_legacy_choice_handoff_v1'}
                if self.backend_distinct_season_ids and not isinstance(self.stores()[0].definition,ChoiceDefinition):
                    from .native_division_season_identity import snapshot as identity_snapshot
                    season,_=self.stores()
                    after['active_match']['division_season_identity']=identity_snapshot(season.load(),before)
                if self.progression_policy is not None:
                    from .account_progression import level_state
                    profile=load_profile(self.account/'profile.json');snapshot=level_state(profile.revival_total_xp or 0)
                    after['active_match']['progression_start']={'total_xp':snapshot['total_xp'],'level':snapshot['level'],
                        'division':before['cycle']['division'],'policy_version':self.progression_policy['version']}
            elif op=='play':
                if before['active_match']['status']=='created' and before['active_match'].get('atomic_match'):
                    from .training_expiry import snapshot as training_snapshot,KEY as TRAINING
                    training=training_snapshot(self.stores()[1])
                    if training is not None:after['active_match'][TRAINING]=training
                    from .injury_effects import snapshot as injury_snapshot,KEY as INJURY
                    injury=injury_snapshot(self.stores()[1])
                    if injury is not None:after['active_match'][INJURY]=injury
                after['active_match'].update(status='playing',play_body_hex=body.hex())
                if after==before:return proposal
            elif op=='end':
                if self.native_atomic_matches:
                    after['active_match']['atomic_end']={'body_hex':body.hex(),'proposal':copy.deepcopy(proposal)}
                    if proposal['outcome']['complete']:
                        from .native_atomic_match import final_state
                        final,final_images=final_state(self,after,{'current':None})
                        self._transaction(before,final,final_images)
                        return proposal
                    self._transaction(before,after,[])
                    return proposal
                observation=proposal['observation'];outcome=proposal['outcome']
                receipt=copy.deepcopy(before['active_match']);receipt.update(status='committed',end_body_hex=body.hex(),
                    result=observation['result'],score=observation['score'],points_after=observation['expected_points'],
                    response=proposal['response'],provenance='original_native_simulation',reward_coins=0,reward_xp=0)
                if receipt.get('native_xp_report') is not None:receipt['reward_xp']=receipt['native_xp_report']['quote']['xp']
                if receipt.get('native_pack_start') is not None:
                    pick=receipt['native_pack_start']['outcomes'][observation['result']]
                    receipt['fixture_pack_delivery']={'definition':pick['definition'],'definition_sha256':pick['definition_sha256'],'classification':'isolated_transport_test'}
                if proposal.get('reward') is not None:
                    reward=copy.deepcopy(proposal['reward'])
                    reward.update(id=str(uuid.uuid5(uuid.UUID(receipt['id']),'native-match-coins')),
                        source_receipt_id=receipt['id'],account_id=before['account_id'],
                        persona_id=before['account_identity']['persona_id'],cycle_id=receipt['cycle_id'],fixture_index=receipt['fixture'],status='committed')
                    profile=json.loads((self.account/'profile.json').read_text());profile['credits']=reward['credits_after']
                    data=encode(profile);reward['profile_after_sha256']=digest(data)
                    receipt['reward_coins']=reward['amount'];receipt['reward']=reward
                    images.append(self._image('profile.json',data))
                after['matches'].append(receipt);after['active_match']=None
                if outcome['complete']:
                    season,_=self.stores();original=season.load()
                    target=outcome['proposed_next_division'];next_id=str(uuid.uuid4())
                    completion={'id':str(uuid.uuid4()),'cycle_id':before['cycle']['id'],'receipt_id':receipt['id'],
                        'policy_version':self.policy.version,'outcome':outcome,'original_pre_final_state':asdict(original),
                        'final_native_result':observation,'next_cycle_id':next_id,'status':'committed','rewards_enabled':False}
                    if self.backend_pack_entitlements:
                        completion['pack_entitlement_policy_version']='backend_pack_entitlement_test_v1'
                    if receipt.get('championship_pack_start') is not None:
                        from .native_championship_packs import delivery as title_delivery
                        completion['championship_pack_start']=copy.deepcopy(receipt['championship_pack_start'])
                        if outcome['preview_band']=='CHAMPIONSHIP':completion['season_pack_delivery']=title_delivery(receipt['championship_pack_start'])
                    after['completions'].append(completion)
                    after['cycle']={'id':next_id,'division':target,'season_id':original.season_id,'status':'awaiting_native_initialization',
                                    'previous_cycle_id':before['cycle']['id'],'initial_native_anchor':None}
                    profile=json.loads((self.account/'profile.json').read_text());profile['division_offline']=target
                    definition=json.loads((self.account/'definition.json').read_text());definition['division_index']=target
                    images=[self._image('profile.json',encode(profile)),self._image('definition.json',encode(definition)),
                            self._image('seasons.json',encode({'persona_id':season.persona_id,'current':None}))]
                if proposal.get('reward') is not None and outcome['complete']:
                    profile['credits']=reward['credits_after']
                    data=encode(profile);reward['profile_after_sha256']=digest(data)
                    images=[i for i in images if i['name']!='profile.json']+[self._image('profile.json',data)]
                if proposal.get('progression') is not None:
                    progression=copy.deepcopy(proposal['progression'])
                    progression.update(id=str(uuid.uuid5(uuid.UUID(receipt['id']),'account-progression')),
                        source_receipt_id=receipt['id'],account_id=before['account_id'],
                        persona_id=before['account_identity']['persona_id'],cycle_id=receipt['cycle_id'],
                        fixture_index=receipt['fixture'],status='committed',certification='backend_only')
                    profile=json.loads((self.account/'profile.json').read_text())
                    profile.update(credits=progression['credits_after'],revival_total_xp=progression['quote']['after']['total_xp'])
                    if outcome['complete']:profile['division_offline']=outcome['proposed_next_division']
                    data=encode(profile);progression['profile_after_sha256']=digest(data)
                    receipt.update(reward_coins=progression['quote']['coins'],reward_xp=progression['quote']['xp'],progression=progression)
                    images=[i for i in images if i['name']!='profile.json']+[self._image('profile.json',data)]
                if outcome['complete'] and receipt.get('season_coin_start') is not None:
                    from .native_season_coin_rewards import quote as season_coin_quote
                    final_profile=next(i for i in images if i['name']=='profile.json')
                    raw_profile=bytes.fromhex(final_profile['after'])
                    completion['season_coin_start']=copy.deepcopy(receipt['season_coin_start'])
                    completion['season_coin_delivery']={'quote':season_coin_quote(receipt['season_coin_start'],outcome['preview_band']),
                        'credits_before':json.loads(raw_profile)['credits'],'profile_before_sha256':digest(raw_profile)}
            self._transaction(before,after,images)
            return proposal
    def observe_initialization(self):
        """Accept only a genuine fresh stock save, after SeasonStore validation."""
        with self.locked():
            before=self._recover(self._load())
            if before['cycle']['status']!='awaiting_native_initialization':return False
            from .season_choice_pending import KEY
            if KEY in before['cycle']:return False
            season,_=self.stores();current=season.load()
            if current is None:return False
            if current.round_number!=1 or current.user_points!=0 or current.division_index!=before['cycle']['division']:
                raise ValueError('Not genuine next-cycle initial state')
            after=copy.deepcopy(before);after['cycle'].update(status='active',initial_native_anchor=asdict(current))
            self._transaction(before,after,[]);return True
