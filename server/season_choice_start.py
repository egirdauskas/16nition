"""Initial competition selection through the existing native season journal.

The client chooses a season and supplies its own empty round-one anchor. Persist
that anchor and the exact advertised fixture definition atomically. No fixture,
reward, wallet or inventory operation is enabled by this bounded candidate.
"""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import re
import uuid

from .account_transaction import atomic, account_locked
from .game_auth import SID
from .local_profile import load_profile
from .local_seasons import SeasonStore, definition_from_data, load_definition
from .native_season_completion import NativeSeasonCoordinator, encode, digest
from .offline_seasons_protocol import parse_season_save
from .season_choices import definition, load_catalog, for_division

VERSION = 'native_season_choice_start_v1'
FIXTURE_SEED = 'read_only_native_preview_v1'


def coordinator(account, fault=None):
    return NativeSeasonCoordinator(account, enabled=True, fault=fault)


def initialize(account):
    """Explicit isolated startup only; existing journals are never reset."""
    c = coordinator(account)
    with c.locked():
        if c.path.exists():
            state = c._recover(c._load())
            if (state['cycle'].get('season_choice_selection') is None and
                    (state['cycle']['status'] != 'awaiting_native_initialization'
                     or state['matches'] or state['completions'] or state['active_match'] is not None
                     or c.stores()[0].load() is not None)):
                raise ValueError('Initial choice candidate cannot adopt a legacy active/historical cycle')
            validate_cycle(state)
            validate_live(c, state)
            return state
        season, _ = c.stores()
        if season.load() is not None: raise ValueError('Fresh stock season selection required')
        division = load_profile(c.account/'profile.json').division_offline
        if division != season.definition.division_index: raise ValueError('Fresh profile/definition mismatch')
        from .first_run_account import account_id as fresh_account_id
        owner = fresh_account_id(c.account) or str(uuid.uuid4())
        state = {'schema': 1, 'account_id': owner, 'account_identity': c.identity(),
            'policy_version': c.policy.version,
            'cycle': {'id': str(uuid.uuid4()), 'division': division, 'season_id': season.definition.season_id,
                      'status': 'awaiting_native_initialization', 'initial_native_anchor': None},
            'active_match': None, 'matches': [], 'completions': [], 'prepared': None}
        atomic(c.path, encode(state))
        return state


def validate_cycle(state):
    from .season_choice_pending import validate as validate_pending
    validate_pending(state)
    from .season_forfeit import validate_legacy_selection
    if validate_legacy_selection(state):return
    cycle = state['cycle']
    source = cycle.get('season_choice_selection')
    if source is None: return
    fields = {'version','competition_key','target','body_hex','fixture_seed','definition_sha256'}
    if type(source) is not dict or set(source) != fields or source['version'] != VERSION:
        raise ValueError('Unknown native competition selection source')
    catalog = load_catalog()
    if source['competition_key'] not in catalog: raise ValueError('Unknown selected competition')
    c = catalog[source['competition_key']]
    expected = definition(c, cycle['season_id'], source['fixture_seed'])
    from .season_choice_preview import identities
    if (cycle['season_id'] != identities(state)[c.key][0] or cycle['division'] != c.division
            or source['fixture_seed'] != FIXTURE_SEED
            or digest(encode(asdict(expected))) != source['definition_sha256']
            or source['target'] != f'/ut/game/fifaworldmobile/season/{expected.season_id}/division/{11-c.division}/user'):
        raise ValueError('Native competition selection identity differs')
    # Validate against an empty store in memory, never write/generate an anchor.
    class EmptySeason(SeasonStore):
        def load(self): return None
    current = parse_season_save(bytes.fromhex(source['body_hex']), EmptySeason(Path('unused'), expected))
    if ((current.round_number,current.user_points) != (1,0)
            or asdict(current) != cycle['initial_native_anchor']):
        raise ValueError('Selection lost its genuine initial anchor')


def validate_live(c, state):
    from .season_forfeit import validate_legacy_selection
    if 'legacy_forfeit_selection' in state['cycle']:
        validate_legacy_selection(state,c.stores()[0].definition)
        if c.stores()[0].load() is None:raise ValueError('Selected legacy season lost its original anchor')
    source = state['cycle'].get('season_choice_selection')
    if source is not None:
        if digest((c.account/'definition.json').read_bytes()) != source['definition_sha256']:
            raise ValueError('Live competition rules changed after selection')
        season, _ = c.stores()
        if season.load() is None: raise ValueError('Selected season lost its original anchor')


def validate_intent(before, after, images):
    source = after['cycle'].get('season_choice_selection')
    if source is None or before['cycle'].get('season_choice_selection') is not None: return False
    from .season_choice_pending import KEY
    handoff=bool(before['matches'] or before['completions'] or KEY in before['cycle'])
    if handoff: validate_handoff(before,allow_prepared=True)
    if (before['active_match'] is not None
            or before['cycle']['status'] != 'awaiting_native_initialization'
            or before['cycle']['initial_native_anchor'] is not None):
        raise ValueError('Cannot replace an active or historical competition')
    validate_cycle(after)
    if len(images) != 2 or {i['name'] for i in images} != {'definition.json','seasons.json'}:
        raise ValueError('Selection may change only rules and original current-season projection')
    expected = copy.deepcopy(before)
    expected['prepared'] = None
    expected['cycle'].update(status='active', season_id=after['cycle']['season_id'],
        initial_native_anchor=after['cycle']['initial_native_anchor'], season_choice_selection=source)
    from .season_choice_pending import KEY
    expected['cycle'].pop(KEY,None)
    if handoff:
        from .season_choice_reference import archive_unreferenced
        image=next((i for i in images if i['name']=='definition.json'),None)
        if image is None:raise ValueError('Missing original definition before selection')
        old_definition=definition_from_data(json.loads(bytes.fromhex(image['before'])))
        expected['season_definition_history']=archive_unreferenced(old_definition,before)
    if after != expected: raise ValueError('Selection changes unrelated journal/account state')
    for image in images:
        old = json.loads(bytes.fromhex(image['before']))
        new = json.loads(bytes.fromhex(image['after']))
        if image['name'] == 'definition.json':
            old_definition, selected = definition_from_data(old), definition_from_data(new)
            if KEY in before['cycle']:
                from .season_choice_reference import snapshot as reference
                original_matches=reference(old_definition)==before['cycle'][KEY]['definition_reference']
                if reference(old_definition) is None:
                    ref=before['cycle'][KEY]['definition_reference']
                    original_matches=(ref.get('version') in ('native_legacy_choice_handoff_v1','native_forfeit_definition_v1') and
                        ref['definition_sha256']==digest(encode(asdict(old_definition))))
            else:
                original_matches=(old_definition.division_index==before['cycle']['division']
                                  and old_definition.season_id==before['cycle']['season_id'])
            if (not original_matches
                    or selected.division_index != before['cycle']['division']
                    or digest(bytes.fromhex(image['after'])) != source['definition_sha256']):
                raise ValueError('Selection definition image differs from advertised source')
        else:
            if old != {'persona_id': before['account_identity']['persona_id'], 'current': None}:
                raise ValueError('Selection would overwrite original season progress')
            if new != {'persona_id': before['account_identity']['persona_id'],
                       'current': after['cycle']['initial_native_anchor']}:
                raise ValueError('Selection changes original anchor or owner')
    return True


def validate_handoff(state, *, allow_prepared=False):
    from .season_forfeit import validate_pending
    if validate_pending(state):
        if state['prepared'] is not None and not allow_prepared:raise ValueError('Forfeiture recovery still pending')
        return
    cycle=state['cycle']
    previous=next((v for v in state['completions'] if v['next_cycle_id']==cycle['id']),None)
    if (state['active_match'] is not None or (state['prepared'] is not None and not allow_prepared)
            or cycle['status']!='awaiting_native_initialization' or cycle['initial_native_anchor'] is not None
            or previous is None or previous['status']!='committed'
            or previous['cycle_id']!=cycle.get('previous_cycle_id')
            or previous['outcome']['proposed_next_division']!=cycle['division']
            or not any(s['id']==previous['receipt_id'] and s['status']=='committed' for s in state['matches'])):
        raise ValueError('Quiescent completed season required for next competition')


def proposal(c, state, method, target, headers, body, *, handoff=False):
    if (method != 'PUT' or headers.get(b'host') != b'10.0.2.2:18081'
            or headers.get(b'x-ut-sid') != SID.encode()
            or headers.get(b'content-length') != str(len(body)).encode()):
        return None
    match = re.fullmatch(r'/ut/game/fifaworldmobile/season/([1-9][0-9]*)/division/([1-9][0-9]*)/user', target)
    if match is None: return None
    validate_cycle(state)
    from .season_forfeit import LEGACY_SELECTION
    legacy=state['cycle'].get(LEGACY_SELECTION)
    if legacy is not None:
        return {'retry':True,'legacy':True} if (legacy['target'],legacy['body_hex'])==(target,body.hex()) else None
    prior = state['cycle'].get('season_choice_selection')
    if prior is not None:
        if (prior['target'],prior['body_hex']) == (target,body.hex()): return {'retry': True}
        return None  # No second choice or rewritten round-one save.
    if handoff:validate_handoff(state)
    if (state['active_match'] is not None or (not handoff and (state['matches'] or state['completions']))
            or state['cycle']['status'] != 'awaiting_native_initialization'):
        return None
    division = load_profile(c.account/'profile.json').division_offline
    if (int(match[2]) != 11-division or state['cycle']['division'] != division): return None
    from .season_choice_preview import identities
    selected = next((x for x in for_division(division) if identities(state)[x.key][0] == int(match[1])), None)
    if selected is None:
        if handoff:
            from .season_forfeit import legacy_selection_proposal
            return legacy_selection_proposal(c,state,method,target,headers,body)
        return None
    rules = definition(selected, int(match[1]), FIXTURE_SEED)
    current = parse_season_save(body, SeasonStore(c.account/'seasons.json', rules)).validate(rules)
    if (current.round_number,current.user_points) != (1,0):
        raise ValueError('Only genuine initial selection accepted')
    source = {'version': VERSION, 'competition_key': selected.key, 'target': target,
              'body_hex': body.hex(), 'fixture_seed': FIXTURE_SEED,
              'definition_sha256': digest(encode(asdict(rules)))}
    after = copy.deepcopy(state)
    after['cycle'].update(status='active', season_id=rules.season_id,
        initial_native_anchor=asdict(current), season_choice_selection=source)
    from .season_choice_pending import KEY
    after['cycle'].pop(KEY,None)
    if handoff:
        from .season_choice_reference import archive_unreferenced
        after['season_definition_history']=archive_unreferenced(c.stores()[0].definition,state)
    images = [c._image('definition.json', encode(asdict(rules))),
              c._image('seasons.json', encode({'persona_id': state['account_identity']['persona_id'], 'current': asdict(current)}))]
    validate_intent(state, after, images)
    return {'retry': False, 'after': after, 'images': images}


@account_locked
def preview(account, method, target, headers, body, *, handoff=False):
    c = coordinator(account)
    with c.locked():
        state = c._recover(c._load())
        validate_live(c, state)
        return proposal(c, state, method, target, headers, body,handoff=handoff)


@account_locked
def commit(account, method, target, headers, body, *, fault=None, handoff=False):
    c = coordinator(account, fault)
    with c.locked():
        state = c._recover(c._load())
        validate_live(c, state)
        p = proposal(c, state, method, target, headers, body,handoff=handoff)
        if p is None: return False
        if not p['retry']: c._transaction(state, p['after'], p['images'])
        return True


def initialize_handoff(account):
    """Recover only selection intents here; never recover a financial operation."""
    c=coordinator(account)
    raw=json.loads(c.path.read_bytes())
    if raw['active_match'] is not None:raise ValueError('Match still active at competition handoff')
    if raw['prepared'] is not None:
        intent=raw['prepared']
        from .season_forfeit import validate_legacy_intent
        if not (validate_intent(raw,intent['state_after'],intent['images']) or
                validate_legacy_intent(raw,intent['state_after'],intent['images'])):
            raise ValueError('Only next-choice recovery allowed')
    state=c.recover()
    if state['cycle'].get('season_choice_selection') or state['cycle'].get('legacy_forfeit_selection'):
        validate_live(c,state)
    else:validate_handoff(state)
    return state
