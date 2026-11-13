"""Disabled, isolated, read-only stock Seasons catalog experiment.

SeasonList01039c00 does not parse a name. Its trophyResourceId leads to the
original static metadata downloader0100a450/0100a640. These service-owned IDs
identify competition metadata, never owned trophy cards or invented artwork.
No StartSeason, match, reward, or account write is implemented here.
"""
from pathlib import Path
import json

from .game_auth import SID
from .identity import json_response
from .season_choices import load_catalog, for_division, fixtures, validate_rule
from .season_revival_policy import load_policy

ACCOUNT = None
SAVES = False
GAMEPLAY = False
HANDOFF = False
CYCLE = False
ADMITTED = False
ROOT = Path(__file__).resolve().parents[1]


def validate_reward_composition(policy, *, cycle=False, source_presentation=False,
                                season_coins=False, atomic_season_rewards=False):
    """Only the existing atomic Store-parity path may accompany choice cycles."""
    if policy is None:
        return
    from .native_match_pack_policy import STORE_PARITY_PATH
    if (not cycle or not source_presentation or not season_coins or not atomic_season_rewards
            or Path(policy).resolve() != STORE_PARITY_PATH.resolve()):
        raise ValueError('Choice packs require isolated cycle/atomic season coins/Store-parity/source captions')


def configure(account=None, *, saves=False, gameplay=False, handoff=False, cycle=False):
    global ACCOUNT, SAVES, GAMEPLAY, HANDOFF, CYCLE, ADMITTED
    ACCOUNT = None
    SAVES = False
    GAMEPLAY = False
    HANDOFF = False
    CYCLE = False
    ADMITTED = False
    if any(type(v) is not bool for v in (saves,gameplay,handoff,cycle)) or sum((saves,gameplay,handoff,cycle))>1:
        raise ValueError('Choose one explicit isolated competition mode')
    if account is None: return
    account = Path(account).resolve()
    if (ROOT/'reports' not in account.parents or account.name != 'isolated-account'
            or not (account/'.lab-snapshot.json').is_file()):
        raise ValueError('Season choices preview requires archived isolated account')
    for file in account.glob('*.json'):
        real = ROOT/'server/data/development/fm16in2026'/file.name
        if file.is_symlink() or real.exists() and file.samefile(real):
            raise ValueError('Account alias refused')
    if handoff:
        from .season_choice_start import initialize_handoff
        initialize_handoff(account)
    elif gameplay or cycle:
        from .season_choice_pending import KEY
        if cycle and KEY in json.loads((account/'native-seasons.json').read_bytes())['cycle']:
            from .season_choice_start import initialize_handoff
            initialize_handoff(account)
        else:_selected(account)
    elif saves:
        from .season_choice_start import initialize
        initialize(account)
    else: _fresh(account)
    from .local_profile import load_profile
    # Validate the whole candidate before accepting the selector.
    season_list(load_profile(account/'profile.json').division_offline)
    ACCOUNT = account
    SAVES = saves or handoff
    GAMEPLAY = gameplay or cycle
    HANDOFF = handoff
    CYCLE = cycle


def configure_fresh(account):
    """Enable the initial catalog only for a validated fresh selected account."""
    global ACCOUNT, SAVES, GAMEPLAY, HANDOFF, CYCLE, ADMITTED
    from .fresh_account_runtime import selected
    if not selected(account):
        raise ValueError('Explicit fresh account selection required')
    configure()
    account = Path(account).resolve()
    from .season_choice_start import initialize, validate_cycle
    journal = account / 'native-seasons.json'
    if journal.exists():
        # Earned reward recovery needs the full runtime coordinator configured
        # below startup, not the initial-selection-only coordinator.
        state = json.loads(journal.read_bytes())
        from .fresh_account_runtime import validate
        if state['account_id'] != validate(account)['account_id']:
            raise ValueError('Fresh Seasons journal belongs to another owner')
        validate_cycle(state)
    else:
        initialize(account)
    from .local_profile import load_profile
    season_list(load_profile(account/'profile.json').division_offline)
    ACCOUNT = account
    SAVES = False
    GAMEPLAY = True
    HANDOFF = False
    CYCLE = True
    ADMITTED = True


def _fresh_initial_selection(state):
    from .season_choice_pending import KEY
    from .fresh_account_runtime import selected
    cycle = state['cycle']
    return (ADMITTED and ACCOUNT is not None
            and selected(ACCOUNT)
            and state['cycle']['status'] == 'awaiting_native_initialization'
            and cycle.get('season_choice_selection') is None
            and not state['matches'] and not state['completions']
            and state['active_match'] is None and state['prepared'] is None
            and KEY not in cycle and 'previous_cycle_id' not in cycle
            and not state.get('season_forfeitures'))

def configure_release(account):
    """Configure the certified path without replacing its current competition."""
    global ACCOUNT,GAMEPLAY,CYCLE,ADMITTED
    from .season_choice_release import selected
    if not selected(account):raise ValueError('Certified choice admission required')
    configure()
    ACCOUNT=Path(account).resolve();GAMEPLAY=CYCLE=ADMITTED=True


def _selected(account):
    """Validate an existing choice; recovery belongs to the configured coordinator.

    Never run the initial-selection-only coordinator over earned reward intents.
    This bounded mode admits only the first fixture, before rollover is supported.
    """
    from .season_choice_start import validate_cycle
    from .local_seasons import load_definition, SeasonStore
    from .native_season_completion import digest
    state = json.loads((account/'native-seasons.json').read_bytes())
    validate_cycle(state)
    source = state['cycle'].get('season_choice_selection')
    if (source is None or state['prepared'] is not None
            or state['cycle']['status'] != 'active'
            or digest((account/'definition.json').read_bytes()) != source['definition_sha256']):
        raise ValueError('Settled genuinely selected competition required')
    store = SeasonStore(account/'seasons.json', load_definition(account/'definition.json'))
    current = store.load()
    if current is None: raise ValueError('Selected competition lost its native anchor')
    return current


def guard_match(account, method, target):
    if (GAMEPLAY and ACCOUNT is not None and Path(account).resolve() == ACCOUNT
            and method == 'POST' and target in ('/ut/game/fifaworldmobile/match',
                                                '/ut/game/fifaworldmobile/match/sim')):
        if not CYCLE and _selected(ACCOUNT).round_number != 1:
            raise ValueError('Bounded competition gameplay admits only its first fixture')


def _fresh(account):
    if ((account/'native-seasons.json').exists()
            or json.loads((account/'seasons.json').read_bytes()) != {'persona_id': 1, 'current': None}):
        raise ValueError('Read-only preview cannot replace an existing season')


def base_identities():
    # Within supplied fcc_trophycards tid1..1024/carddbid8200000..8204095.
    # Stable for this version; do not alias an existing issued definition.
    return {key: (101+i, 8203000+i) for i, key in enumerate(load_catalog())}


def identities(state=None):
    base=base_identities();result=dict(base)
    if state is None and ADMITTED and ACCOUNT is not None:
        state=json.loads((ACCOUNT/'native-seasons.json').read_bytes())
    if state is not None:
        from .season_forfeit import validate_record
        for row in state.get('season_forfeitures',[]):
            alias=row.get('catalog_alias')
            if alias is None:continue
            validate_record(state,row)
            key=alias['competition_key'];value=(alias['season_id'],alias['metadata_resource_id'])
            if result[key]!=base[key] and result[key]!=value:
                raise ValueError('Conflicting forfeiture catalog identities')
            result[key]=value
        if len({v[0] for v in result.values()})!=len(result):
            raise ValueError('Forfeiture catalog identity collision')
    return result


def eligibility(competition):
    """Only independently mapped native predicates; unknowns fail closed."""
    result = []
    for slot, rule in enumerate(competition.rules, 1):
        validate_rule(rule)
        #01017344 selects primary key;01019adc handles counted named-domain
        #matches (key2 + league specifier11). Keys7/5 count distinct nations /
        #largest same-league group.01012688 maps key14 values0,1,2 to masks1,2,4.
        primary = {'chemistry': 1, 'distinct_nationalities': 7,
                   'players_sharing_league': 5, 'players_from_named_league': 2}[rule['kind']]
        pairs = [(primary, rule['value']), (13, {'>=': 0, '==': 2}[rule['operator']])]
        if rule['kind'] == 'players_from_named_league': pairs.append((11, rule['league_id']))
        if rule['kind'] != 'chemistry':
            pairs.append((14, 0))
            if rule['scope'] == 'starting11_and_substitutes': pairs.append((14, 1))
        for key, value in pairs:
            result.append({'eligibilitySlot': slot, 'eligibilityKey': key, 'eligibilityValue': value})
    return result


def season_list(division):
    ids = identities()
    thresholds = load_policy().for_division(division).threshold_blocks()
    rows = []
    for competition in for_division(division):
        season_id, metadata_id = ids[competition.key]
        rows.append({'id': season_id, 'type': 'OFFLINE', 'trophyResourceId': metadata_id,
            'divisionId': 11-division, 'numMatches': 10, 'matchLengthMin': 6,
            'untilStartSeconds': 0, 'untilEndSeconds': 2147483647,
            'elgOperation': 'AND', 'elgReq': eligibility(competition),
            'prizeSet': [dict(block, awardMappings=[]) for block in thresholds],
            'matches': [{'teamId': f.team_id, 'difficulty': f.difficulty,
                'roundId': f.round_number, 'rewardMult': 0, 'coins': 0}
                for f in fixtures(competition, 'read_only_native_preview_v1')]})
    return {'seasons': rows}


def metadata(competition):
    season_id, _ = identities()[competition.key]
    from .season_trophy_art import metadata_art
    # Order matters:0100a640 creates SEASON_LOC_id at tournamentType, then
    #0100e124 adds label for the native eng_us locale. No fabricated artwork.
    return {'tournamentId': season_id, 'tournamentType': 4,
            **metadata_art(competition),
            'locString': [{'lang': 'eng_us', 'label': competition.name}]}


def response_for(method, target, headers, body, account, *, after_recovery=False):
    if ACCOUNT is None or account is None or Path(account).resolve() != ACCOUNT:
        return None
    if GAMEPLAY and not after_recovery: return None
    if CYCLE and method=='PUT' and target.startswith('/ut/game/fifaworldmobile/season/'):
        from .season_choice_pending import KEY
        state=json.loads((ACCOUNT/'native-seasons.json').read_bytes())
        if KEY in state['cycle']:
            from .season_choice_start import preview
            return json_response({}) if preview(ACCOUNT,method,target,headers,body,handoff=True) is not None else None
        if _fresh_initial_selection(state):
            from .season_choice_start import preview
            return json_response({}) if preview(ACCOUNT,method,target,headers,body) is not None else None
    if SAVES and method == 'PUT':
        from .season_choice_start import preview
        return json_response({}) if preview(ACCOUNT, method, target, headers, body,handoff=HANDOFF) is not None else None
    if (method != 'GET' or body or headers.get(b'host') != b'10.0.2.2:18081'
            or headers.get(b'content-length', b'0') != b'0'):
        return None
    if GAMEPLAY:
        from .season_choice_pending import KEY
        state=json.loads((ACCOUNT/'native-seasons.json').read_bytes())
        if CYCLE and KEY in state['cycle']:
            from .season_choice_start import validate_handoff
            validate_handoff(state)
        elif ADMITTED and state['cycle'].get('season_choice_selection') is None:
            if not _fresh_initial_selection(state):
                # A grandfathered legacy competition retains its exact stock catalog.
                return None
        elif not _fresh_initial_selection(state):
            _selected(ACCOUNT)
    elif SAVES:
        from .season_choice_start import initialize,initialize_handoff
        (initialize_handoff if HANDOFF else initialize)(ACCOUNT)
    else: _fresh(ACCOUNT)
    from .local_profile import load_profile
    division = load_profile(ACCOUNT/'profile.json').division_offline
    path = f'/ut/game/fifaworldmobile/season/list?active=true&count=99&divisionList={11-division}&type=offline'
    if target == path and headers.get(b'x-ut-sid') == SID.encode():
        return json_response(season_list(division))
    ids = identities()
    for competition in for_division(division):
        if target == f'/fut/items/android/{ids[competition.key][1]}.json':
            return json_response(metadata(competition))
    return None


def commit_request(method, target, headers, body, account):
    if CYCLE and ACCOUNT is not None and account is not None and Path(account).resolve()==ACCOUNT and method=='PUT' and target.startswith('/ut/game/fifaworldmobile/season/') and target.endswith('/user'):
        from .season_choice_pending import KEY
        state=json.loads((ACCOUNT/'native-seasons.json').read_bytes())
        if KEY in state['cycle']:
            from .season_choice_start import commit
            if not commit(ACCOUNT,method,target,headers,body,handoff=True):raise ValueError('Next choice changed before commit')
            return True
        if _fresh_initial_selection(state):
            from .season_choice_start import commit
            if not commit(ACCOUNT, method, target, headers, body):
                raise ValueError('Initial fresh choice changed before commit')
            return True
    if (not SAVES or ACCOUNT is None or account is None or Path(account).resolve() != ACCOUNT
            or method != 'PUT' or not target.startswith('/ut/game/fifaworldmobile/season/')):
        return False
    from .season_choice_start import commit
    if not commit(ACCOUNT, method, target, headers, body,handoff=HANDOFF):
        raise ValueError('Initial selection changed between preview and commit; refuse stale acknowledgment')
    return True
