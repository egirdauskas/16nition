"""ACCOMP-001 permanent Accomplishments (explicit revival_policy, user design 5 Nov 2026).

Stock contracts (reports/accomp-001/2026-11-05-contracts/report.md):
- GET Challenge/GetChallenges (1453/1485): ChallengeCategories/ChallengeCategory
  {CategoryId, CategoryName, ChallengeList/Challenge, TileAssetId} + Version.
- GET /loc/en_us/Challenges.xml (1485): XLIFF; challenge texts are its resnames (1490).
- GET Challenge/GetPersonaAccomplishments: <Accomplishment> records
  {ChallengeId, CompletedTimes, IsLocked, RewardsToClaim, StepsCompleted} (1489).
- POST Challenge/GetDetails (1480): LongList of ids -> root of Challenge elements.
- GET Challenge/GetRewardsToClaim (1488/1494): root of <ChallengeReward>
  {ChallengeId, IsDelayedRedemption, LevelUpInfo, RewardDetailList, RewardId}.
- GET Challenge/ClaimReward?rewardId=N (1494): one record with the same fields
  directly under the root (handler 00303930).
The client needs user.ini ONLINE/CHALLENGE_PATH_LOC_TEXT,
CHALLENGE_CATEGORY_PATH_TILE_ASSET and CHALLENGE_PATH_BADGE_ASSET (1487/1488).

Design: progress counts only what happens after enabling (no back pay). Goals
come from stock ScoreAGoal events and count once their match is committed.
A claim credits coins, one untradeable pack and/or one untradeable special card
through one prepared multi-file intent; RewardId is the ChallengeId, so a claim
retry returns the recorded reply without crediting again.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import time
import uuid
from xml.sax.saxutils import escape

from .account_transaction import account_locked, atomic, recover_images

POLICY_PATH = Path(__file__).parent / 'policy/accomplishments-v1.json'
VERSION = 'accomplishments_v1'
SELECTOR = 'accomplishments-select.json'
STATE = 'accomplishments.json'
SOURCE_KIND = 'accomplishment'
NS = 'http://schemas.datacontract.org/2004/07/Victory.Challenge.TransferObjects'
ENGINE = '/victory_fwm_s2/Engine.svc/Challenge/'
CHALLENGES = ENGINE + 'GetChallenges'
DETAILS = ENGINE + 'GetDetails'
PROGRESS = ENGINE + 'GetPersonaAccomplishments'
REWARDS_TO_CLAIM = ENGINE + 'GetRewardsToClaim'
CLAIM = ENGINE + 'ClaimReward'
LOCALIZATION = '/loc/en_us/Challenges.xml'
METRICS = {'goals', 'played', 'wins', 'clean_sheets', 'big_wins', 'division_reached',
           'division_title', 'market_buys', 'market_sells'}
FILTER_KEYS = {'country', 'shot_type', 'situation', 'min_distance', 'division'}
_POLICY_CACHE = {}


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


# --- Policy ------------------------------------------------------------------

def _validated_policy(raw):
    value = json.loads(raw)
    keys = {'version', 'classification', 'approved', 'default_enabled', 'challenge_version',
            'start_date', 'categories', 'challenges'}
    if (type(value) is not dict or set(value) != keys or value['version'] != VERSION
            or value['classification'] != 'revival_policy' or value['default_enabled'] is not False
            or type(value['challenge_version']) is not int or value['challenge_version'] < 1):
        raise ValueError('Invalid accomplishments policy')
    categories = {c['id'] for c in value['categories']}
    if len(categories) != len(value['categories']) or not value['challenges']:
        raise ValueError('Invalid accomplishment categories')
    from .reward_store_parity import policy as parity
    packs = {name: row['definition'] for name, row in parity()['bindings'].items()}
    seen = set()
    for row in value['challenges']:
        if (type(row['id']) is not int or row['id'] in seen or row['category'] not in categories
                or row['metric'] not in METRICS or type(row['target']) is not int or row['target'] < 1
                or set(row.get('filter', {})) - FILTER_KEYS
                or set(row['reward']) - {'coins', 'pack', 'card'}
                or type(row['reward'].get('coins', 0)) is not int or row['reward'].get('coins', 0) < 0):
            raise ValueError('Invalid accomplishment challenge %r' % row.get('id'))
        if 'pack' in row['reward'] and row['reward']['pack'] not in packs:
            raise ValueError('Accomplishment pack must be an existing untradeable reward pack')
        if 'card' in row['reward']:
            _card(row['reward']['card'])
        also = row.get('also')
        if also is not None and (row['metric'] != 'goals' or set(also) != {'filter', 'target'}
                                 or set(also['filter']) - FILTER_KEYS or also['target'] < 1):
            raise ValueError('Invalid accomplishment sub-target')
        if not any(row['reward'].values()):
            raise ValueError('Accomplishment without reward')
        seen.add(row['id'])
    return value


def policy():
    raw = POLICY_PATH.read_bytes()
    digest = hashlib.sha256(raw).digest()
    if digest not in _POLICY_CACHE:
        _POLICY_CACHE[digest] = _validated_policy(raw)
    return deepcopy(_POLICY_CACHE[digest])


def pack_definition(name):
    from .reward_store_parity import policy as parity
    return parity()['bindings'][name]['definition']


def allowed_pack_definitions():
    return {pack_definition(row['reward']['pack']) for row in policy()['challenges'] if 'pack' in row['reward']}


def _card(record_id):
    """(base resource, record) of one reviewed supplied special card."""
    from .reconstructed_specials import reviewed_pool
    for special in reviewed_pool():
        if special.record_id == record_id:
            return special.base_resource_id, record_id
    raise ValueError('Accomplishment card is not a reviewed supplied special')


def challenge(challenge_id):
    return next((c for c in policy()['challenges'] if c['id'] == challenge_id), None)


# --- Selection and state ----------------------------------------------------

def enabled(account):
    """Per-account selector; a copy bound to another account stays inactive."""
    if account is None:
        return False
    account = Path(account).resolve()
    marker = account / SELECTOR
    if not marker.exists():
        return False
    if marker.is_symlink():
        raise ValueError('Accomplishments selector must be a regular file')
    value = json.loads(marker.read_bytes())
    if (type(value) is not dict or set(value) != {'version', 'account', 'policy_sha256'}
            or value['version'] != VERSION):
        raise ValueError('Invalid accomplishments selector')
    if value['account'] != str(account):
        return False
    if value['policy_sha256'] != sha(POLICY_PATH.read_bytes()):
        raise ValueError('Accomplishments policy changed after selection')
    return (account / STATE).is_file()


def marker_for(account):
    policy()
    return {'version': VERSION, 'account': str(Path(account).resolve()),
            'policy_sha256': sha(POLICY_PATH.read_bytes())}


def _empty_state(account, now):
    seasons = Path(account) / 'native-seasons.json'
    matches = completions = 0
    if seasons.exists():
        value = json.loads(seasons.read_bytes())
        matches = len(value['matches'])
        completions = len(value['completions'])
    return {'version': VERSION, 'enabled_at': int(now), 'seasons_baseline': matches,
            'completions_baseline': completions, 'goals': [], 'matches': [], 'claims': [],
            'prepared': None}


def enable(account, now=None):
    """Select the feature: progress starts now (no back pay)."""
    account = Path(account).resolve()
    if (account / STATE).exists() or (account / SELECTOR).exists():
        raise FileExistsError('Accomplishments already enabled')
    atomic(account / STATE, encode(_empty_state(account, now if now is not None else time.time())))
    atomic(account / SELECTOR, encode(marker_for(account)))


@account_locked
def ensure_enabled(account):
    """Initialize selected first-run functionality once, without back pay.

    A crash after the empty state write can finish publishing its selector.
    Existing progress/claims are never reset or silently adopted from another
    account; a selector without its state is an error, not a new initialization.
    """
    account = Path(account).resolve()
    state_path, selector_path = account / STATE, account / SELECTOR
    for path in (state_path, selector_path):
        if path.is_symlink() or path.exists() and path.stat().st_nlink != 1:
            raise ValueError('Accomplishments initialization alias refused')
    if selector_path.exists():
        if not enabled(account):
            raise ValueError('Accomplishments selection/state differs from account')
        load_state(account)
        return False
    if state_path.exists():
        value = load_state(account)
        if value['goals'] or value['matches'] or value['claims'] or value['prepared'] is not None:
            raise ValueError('Cannot adopt unselected Accomplishments history')
    else:
        atomic(state_path, encode(_empty_state(account, time.time())))
    atomic(selector_path, encode(marker_for(account)))
    return True


def _validated_state(raw):
    value = json.loads(raw)
    keys = {'version', 'enabled_at', 'seasons_baseline', 'completions_baseline', 'goals', 'matches',
            'claims', 'prepared'}
    if (type(value) is not dict or set(value) != keys or value['version'] != VERSION
            or any(type(value[k]) is not int or value[k] < 0
                   for k in ('enabled_at', 'seasons_baseline', 'completions_baseline'))
            or any(type(value[k]) is not list for k in ('goals', 'matches', 'claims'))):
        raise ValueError('Invalid accomplishments state')
    digests = [g['sha256'] for g in value['goals']]
    claimed = [c['challenge_id'] for c in value['claims']]
    sources = [m['source_id'] for m in value['matches']]
    if len(set(digests)) != len(digests) or len(set(claimed)) != len(claimed) or len(set(sources)) != len(sources):
        raise ValueError('Duplicate accomplishments record')
    return value


def load_state(account):
    return _validated_state((Path(account) / STATE).read_bytes())


def validate_file(account):
    """Read-only backup check (selector and state together)."""
    path = Path(account) / STATE
    if path.exists():
        value = _validated_state(path.read_bytes())
        if value['prepared'] is not None:
            raise ValueError('Recover pending accomplishment claim before backup')


# --- Recording (stock event hooks) --------------------------------------------

@account_locked
def record_goal(account, body, values):
    """Keep one stock ScoreAGoal event until its match commits (retries dedupe)."""
    if not enabled(account) or 'MatchId' not in values:
        return
    value = load_state(account)
    digest = sha(body)
    if any(g['sha256'] == digest for g in value['goals']):
        return
    try:
        distance = int(values.get('ShotDistanceYard', '0'))
    except ValueError:
        distance = 0
    value['goals'].append({
        'sha256': digest, 'match_id': str(values['MatchId']),
        'country': int(values.get('PlayerCountryId', 0)),
        'shot_type': values.get('ShotType'), 'situation': values.get('GoalSituation'),
        'distance': distance,
    })
    atomic(Path(account) / STATE, encode(value))


def _report_goals(receipt):
    report = (receipt or {}).get('report') or {}
    raw = bytes.fromhex(report.get('body_hex', '')).decode('utf-8', 'replace')
    player = re.search(r'<PlayerStats>(.*?)</PlayerStats>', raw, re.S)
    stats = dict(re.findall(r'<Key>(\w+)</Key><Value>(-?\d+)</Value>', player.group(1))) if player else {}
    if 'Goals' not in stats or 'GoalsAgainst' not in stats:
        return None
    return int(stats['Goals']), int(stats['GoalsAgainst'])


@account_locked
def record_tournament_match(account, source_id, match_id, receipt):
    """One committed tournament match (result from its stored reward receipt)."""
    if not enabled(account) or not receipt or receipt.get('result') not in ('W', 'D', 'L'):
        return
    value = load_state(account)
    if any(m['source_id'] == source_id for m in value['matches']):
        return
    score = _report_goals(receipt)
    seasons = Path(account) / 'native-seasons.json'
    # Position among Seasons matches, so the User Bio form can order both kinds.
    after_season = len(json.loads(seasons.read_bytes())['matches']) if seasons.exists() else 0
    value['matches'].append({'source_id': source_id, 'match_id': str(match_id),
                             'result': receipt['result'],
                             'goals_for': score[0] if score else None,
                             'goals_against': score[1] if score else None,
                             'after_season': after_season})
    atomic(Path(account) / STATE, encode(value))


# --- Progress -----------------------------------------------------------------

def _season_matches(account, value):
    """Committed, non-forfeit Seasons matches since enabling."""
    path = Path(account) / 'native-seasons.json'
    if not path.exists():
        return [], []
    from .native_match_session import session_id
    seasons = json.loads(path.read_bytes())
    rows = []
    for match in seasons['matches'][value['seasons_baseline']:]:
        if match.get('status') != 'committed' or match.get('native_match_forfeit'):
            continue
        score = match.get('score')
        rows.append({'match_id': str(session_id(match['id'])), 'result': match.get('result'),
                     'goals_for': score[0] if score else None, 'goals_against': score[1] if score else None})
    completions = [c for c in seasons['completions'][value['completions_baseline']:]
                   if c.get('status') == 'committed']
    return rows, completions


def _market(account, since):
    path = Path(account) / 'market.json'
    if not path.exists():
        return 0, 0
    buys = sells = 0
    for listing in json.loads(path.read_bytes())['listings']:
        settled = listing.get('settlement') or {}
        if settled.get('at', 0) < since:
            continue
        if settled.get('buyer') == 'player':
            buys += 1
        elif listing.get('seller') == 'player' and settled.get('buyer') == 'bot':
            sells += 1
    return buys, sells


def _goal_matches(goal, flt):
    if 'country' in flt and goal['country'] != flt['country']:
        return False
    if 'shot_type' in flt and goal['shot_type'] != flt['shot_type']:
        return False
    if 'situation' in flt and goal['situation'] != flt['situation']:
        return False
    return goal['distance'] >= flt.get('min_distance', 0)


def facts(account, value=None):
    """Everything progress is computed from (pure function of the stores)."""
    value = value or load_state(account)
    seasons, completions = _season_matches(account, value)
    matches = seasons + value['matches']
    committed = {m['match_id'] for m in matches}
    goals = [g for g in value['goals'] if g['match_id'] in committed]
    reached = set()
    titles = set()
    for completion in completions:
        outcome = completion.get('outcome') or {}
        if outcome.get('outcome') in ('promotion', 'championship') and outcome.get('proposed_next_division'):
            reached.add(outcome['proposed_next_division'])
        if outcome.get('outcome') == 'championship':
            titles.add(outcome.get('division'))
    buys, sells = _market(account, value['enabled_at'])
    scored = [m for m in matches if m['goals_for'] is not None and m['goals_against'] is not None]
    return {
        'goals': goals, 'played': len(matches),
        'wins': sum(m['result'] == 'W' for m in matches),
        'clean_sheets': sum(m['goals_against'] == 0 for m in scored),
        'big_wins': sum(m['goals_for'] - m['goals_against'] >= 3 for m in scored),
        'reached': reached, 'titles': titles, 'market_buys': buys, 'market_sells': sells,
    }


def total_steps(row):
    return row['target'] + (row['also']['target'] if row.get('also') else 0)


def steps(row, f):
    metric = row['metric']
    flt = row.get('filter', {})
    if metric == 'goals':
        done = min(row['target'], sum(_goal_matches(g, flt) for g in f['goals']))
        if row.get('also'):
            sub = row['also']
            done += min(sub['target'], sum(_goal_matches(g, sub['filter']) for g in f['goals']))
        return done
    if metric == 'division_reached':
        return 1 if any(d <= flt['division'] for d in f['reached']) else 0
    if metric == 'division_title':
        return 1 if flt['division'] in f['titles'] else 0
    return min(row['target'], f[metric])


def progress(account):
    """{challenge_id: (steps, total, claimed)}."""
    value = load_state(account)
    f = facts(account, value)
    claimed = {c['challenge_id'] for c in value['claims']}
    return {row['id']: (steps(row, f), total_steps(row), row['id'] in claimed)
            for row in policy()['challenges']}


# --- XML ----------------------------------------------------------------------

def _text_keys(row):
    return 'ACCOMP_%d_NAME' % row['id'], 'ACCOMP_%d_DESC' % row['id']


def _reward_details(row):
    reward = row['reward']
    parts = []
    if reward.get('coins'):
        parts.append('<RewardDetail><RewardCount>%d</RewardCount><RewardDefinitionId>0</RewardDefinitionId>'
                     '<RewardType>Coin</RewardType></RewardDetail>' % reward['coins'])
    # Packs are named in the description instead: the stock list/Redeem widgets
    # can only label a Pack reward Bronze/Silver/Gold/Mixed and showed every
    # revival pack id as "Bronze" (1495/1496).
    return ''.join(parts)


def _challenge_xml(row, value):
    name, desc = _text_keys(row)
    details = _reward_details(row)
    first = '<RewardDetailFirstTimeList>%s</RewardDetailFirstTimeList>' % details if details else ''
    # Permanent: no DisplayUntilDate/EndDate, so no countdown is shown (1498).
    return ('<Challenge><BadgeAssetId>0</BadgeAssetId><CategoryId>%d</CategoryId><ChallengeId>%d</ChallengeId>'
            '<IsDelayedRedeemtion>true</IsDelayedRedeemtion><IsOneTime>true</IsOneTime>'
            '<LongDescription>%s</LongDescription>%s<ShortDescription>%s</ShortDescription>'
            '<StartDate>%s</StartDate><TotalSteps>%d</TotalSteps></Challenge>'
            % (row['category'], row['id'], desc, first, name, value['start_date'], total_steps(row)))


def challenge_version(account):
    """Changes whenever a challenge completes, so the stock client refetches.

    CycleSession ShortMessage ChallengeVersion (1452/1453) raises
    AccomplishmentDataChanged when it differs from the Version of the last
    accepted GetChallenges reply (client+0x118); the refetched list is followed
    by GetRewardsToClaim, which fills the Redeem screen.
    """
    done = sum(1 for d, total, _ in progress(account).values() if d >= total)
    return policy()['challenge_version'] * 1_000_000 + done


def short_messages(account):
    """CycleSession ShortMessages element for a selected account ('' otherwise)."""
    try:
        if not enabled(account):
            return ''
        return ('<ShortMessages><ShortMessage><Type>ChallengeVersion</Type><Value>%d</Value>'
                '</ShortMessage></ShortMessages>' % challenge_version(account))
    except (ValueError, KeyError, TypeError, OSError):
        return ''


def challenges_xml(account=None):
    value = policy()
    categories = []
    for category in value['categories']:
        rows = [r for r in value['challenges'] if r['category'] == category['id']]
        categories.append(
            '<ChallengeCategory><CategoryId>%d</CategoryId><CategoryName>ACCOMP_CAT_%d</CategoryName>'
            '<ChallengeList>%s</ChallengeList><TileAssetId>0</TileAssetId></ChallengeCategory>'
            % (category['id'], category['id'], ''.join(_challenge_xml(r, value) for r in rows)))
    version = challenge_version(account) if account is not None else value['challenge_version'] * 1_000_000
    return ('<Response xmlns="%s"><ChallengeCategories>%s</ChallengeCategories><Version>%d</Version></Response>'
            % (NS, ''.join(categories), version)).encode()


def details_xml(ids):
    value = policy()
    rows = [r for r in value['challenges'] if r['id'] in ids]
    return ('<ArrayOfChallenge xmlns="%s">%s</ArrayOfChallenge>'
            % (NS, ''.join(_challenge_xml(r, value) for r in rows))).encode()


def description(row):
    """Challenge text plus the pack it awards (the stock UI cannot name packs)."""
    pack = row['reward'].get('pack')
    return row['description'] + (' + %s Pack' % pack if pack else '')


# Stock keys whose text the online service used to deliver. Skill Games (Quick
# Events) download drill scripts (.tg) that are not in the supplied files; the
# select screen title says so instead (user, 6 Nov 2026; screen 1524).
NOTICE_TEXTS = {
    'LTXT_MOB_SG_SELECT_EVENT': 'Skill Games are not implemented yet. Maybe later!',
}


def localization_xml():
    value = policy()
    units = [('ACCOMP_CAT_%d' % c['id'], c['name']) for c in value['categories']]
    for row in value['challenges']:
        name, desc = _text_keys(row)
        units += [(name, row['name']), (desc, description(row))]
    units += list(NOTICE_TEXTS.items())
    from .welcome_gift import localization_units
    units += localization_units()
    body = ''.join('<trans-unit id="%s" resname="%s"><source>%s</source></trans-unit>'
                   % (key, key, escape(text)) for key, text in units)
    return ('<?xml version="1.0" encoding="UTF-8"?><xliff version="1.2"><file source-language="en-US" '
            'datatype="plaintext" original="Challenges"><body>%s</body></file></xliff>' % body).encode()


def progress_xml(account):
    rows = []
    for cid, (done, total, claimed) in sorted(progress(account).items()):
        complete = done >= total
        rows.append('<Accomplishment><ChallengeId>%d</ChallengeId><CompletedTimes>%d</CompletedTimes>'
                    '<IsLocked>false</IsLocked><RewardsToClaim>%d</RewardsToClaim>'
                    '<StepsCompleted>%d</StepsCompleted></Accomplishment>'
                    % (cid, 1 if complete else 0, 1 if complete and not claimed else 0, done))
    return ('<Response xmlns="%s">%s</Response>' % (NS, ''.join(rows))).encode()


def _reward_fields(row):
    details = _reward_details(row)
    listing = '<RewardDetailList>%s</RewardDetailList>' % details if details else ''
    return ('<ChallengeId>%d</ChallengeId><IsDelayedRedemption>true</IsDelayedRedemption>%s'
            '<RewardId>%d</RewardId>' % (row['id'], listing, row['id']))


def rewards_to_claim_xml(account):
    ready = [cid for cid, (done, total, claimed) in sorted(progress(account).items())
             if done >= total and not claimed]
    body = ''.join('<ChallengeReward>%s</ChallengeReward>' % _reward_fields(challenge(cid)) for cid in ready)
    return ('<Response xmlns="%s">%s</Response>' % (NS, body)).encode()


def claim_xml(row):
    return ('<Response xmlns="%s">%s</Response>' % (NS, _reward_fields(row))).encode()


# --- Claim (one prepared multi-file intent) -------------------------------------

class _Stores:
    def __init__(self, account):
        from .local_content import ContentCatalog
        from .local_football import FootballStore
        from .local_packs import PackStore
        from .local_profile import ProfileStore
        self.account = Path(account)
        self.profile = ProfileStore(self.account / 'profile.json')
        self.packs = PackStore(self.account / 'packs.json')
        self.football = FootballStore(self.account / 'football.json',
                                      ContentCatalog(self.account / 'content.json'))

    @contextmanager
    def locked(self):
        # Same packs -> profile -> football ordering as purchases and FreeCoins.
        with self.packs.transaction(), self.profile.transaction(), self.football.transaction():
            yield


def _pack_owner(account, packs):
    for grant in packs.get('source_grants', []):
        return grant['account_id']
    seasons = Path(account) / 'native-seasons.json'
    if seasons.exists():
        return json.loads(seasons.read_bytes())['account_id']
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'accomplishments:' + str(Path(account).resolve())))


def _formation(challenge_id):
    from .local_formations import FORMATIONS
    ordered = sorted(FORMATIONS)
    digest = hashlib.sha256(('accomplishment-formation:%d' % challenge_id).encode()).digest()
    return ordered[int.from_bytes(digest[:4], 'big') % len(ordered)]


def _images(stores, row):
    """(images, claim record) for one claim; pure function of the current stores."""
    from .local_profile import validate_credits
    reward = row['reward']
    persona = stores.profile.load().persona_id
    profile_raw = stores.profile.path.read_bytes()
    packs_raw = stores.packs.path.read_bytes() if stores.packs.path.exists() else None
    football_raw = stores.football.path.read_bytes()
    record = {'challenge_id': row['id'], 'coins': reward.get('coins', 0), 'pack': None, 'card': None}
    images = []
    profile = json.loads(profile_raw)
    before = profile['credits']
    profile['credits'] = validate_credits(before + record['coins'])
    record['credits_before'] = before
    record['credits_after'] = profile['credits']
    images.append({'name': 'profile.json', 'before': profile_raw.hex(), 'after': encode(profile).hex()})
    if reward.get('pack'):
        if packs_raw is None:
            raise ValueError('Pack store required for an accomplishment pack')
        from .local_packs import PackStore
        packs = json.loads(packs_raw)
        source = uuid.uuid5(uuid.NAMESPACE_URL, 'accomplishment:%d' % row['id'])
        receipt = {'reward_id': str(uuid.uuid5(source, SOURCE_KIND + '-pack')), 'source_id': str(source),
                   'source_kind': SOURCE_KIND, 'account_id': _pack_owner(stores.account, packs),
                   'persona_id': persona, 'cycle_id': str(uuid.uuid5(source, 'cycle')),
                   'policy_version': VERSION, 'certification': 'backend_only'}
        after, grant = PackStore.source_grant_image(packs, pack_definition(reward['pack']), receipt)
        PackStore(stores.packs.path)._validated(encode(after), persona)
        record['pack'] = {'definition': grant['entitlement']['definition'],
                          'catalog_id': grant['entitlement']['catalog_id'], 'reward_id': grant['reward_id']}
        images.append({'name': 'packs.json', 'before': packs_raw.hex(), 'after': encode(after).hex()})
    if reward.get('card'):
        resource, special = _card(reward['card'])
        football = json.loads(football_raw)
        instance = football['next_instance_id']
        football['owned_items'] = sorted(football['owned_items'] + [{
            'fitness': 99, 'formation_id': _formation(row['id']), 'instance_id': instance, 'morale': 99,
            'resource_id': resource, 'special_version_id': special}], key=lambda i: i['instance_id'])
        football['inventory_locations'] = football.get('inventory_locations', []) + [
            {'instance_id': instance, 'pile': 'unassigned'}]
        football['untradeable_instance_ids'] = football.get('untradeable_instance_ids', []) + [instance]
        football['next_instance_id'] = instance + 1
        state = stores.football.decode(football, persona)
        canonical = encode(stores.football.encoded(state))
        record['card'] = {'record_id': special, 'resource_id': resource, 'instance_id': instance}
        images.append({'name': 'football.json', 'before': football_raw.hex(), 'after': canonical.hex()})
    return images, record


def _recover(account, value):
    if value['prepared'] is None:
        return value
    prepared = value['prepared']
    recover_images(Path(account), prepared['images'])
    after = prepared['state_after']
    atomic(Path(account) / STATE, encode(after))
    return after


@account_locked
def recover(account):
    if not enabled(account):
        return
    stores = _Stores(account)
    with stores.locked():
        _recover(account, load_state(account))


@account_locked
def claim(account, challenge_id):
    """Reply bytes for one claim; credits once, retries return the same reply."""
    row = challenge(challenge_id)
    if row is None:
        raise ValueError('Unknown accomplishment reward')
    stores = _Stores(account)
    with stores.locked():
        value = _recover(account, load_state(account))
        if any(c['challenge_id'] == challenge_id for c in value['claims']):
            return claim_xml(row)
        f = facts(account, value)
        if steps(row, f) < total_steps(row):
            raise ValueError('Accomplishment not completed')
        images, record = _images(stores, row)
        record['at'] = int(time.time())
        after = deepcopy(value)
        after['claims'].append(record)
        value['prepared'] = {'images': images, 'state_after': after}
        atomic(Path(account) / STATE, encode(value))
        _recover(account, value)
        return claim_xml(row)


# --- HTTP ---------------------------------------------------------------------

def _session_ok(headers):
    from .local_profile import load_profile
    profile = load_profile()
    return (headers.get(b'host') == b'10.0.2.2:18081'
            and headers.get(b'securitytoken') == profile.victory_security_token.encode()
            and headers.get(b'userid') == profile.user_id.encode())


def response_for(method, target, headers, body):
    """Replies for the captured Challenge routes when this account selected the feature."""
    from . import local_profile
    from .victory_session import xml_response
    account = local_profile.PROFILE_PATH.resolve().parent
    try:
        if not enabled(account):
            from .first_run_account import pending_session, receipt as setup_receipt, RECEIPT
            first_run = pending_session(account) is not None
            if not first_run and (account / RECEIPT).is_file():
                setup_receipt(account)
                first_run = True
            if first_run and method == 'GET' and not body:
                # The installed stock config fetches challenge texts/list before
                # login finalization. A fresh club has no admitted challenge
                # state yet: serve an empty catalog, never infer earned rewards.
                if target == LOCALIZATION and headers.get(b'host') == b'10.0.2.2:18081':
                    from .welcome_gift import note
                    note('localization', account)
                    return xml_response(localization_xml())
                if target == CHALLENGES and _session_ok(headers):
                    return xml_response(('<Response xmlns="%s"><ChallengeCategories/>'
                                         '<Version>0</Version></Response>' % NS).encode())
                if target == REWARDS_TO_CLAIM and _session_ok(headers):
                    return xml_response(('<Response xmlns="%s"/>' % NS).encode())
            return None
        if method == 'GET' and target == LOCALIZATION and not body:
            if headers.get(b'host') != b'10.0.2.2:18081':
                return None
            reply = xml_response(localization_xml())
            from .welcome_gift import note
            note('localization', account)
            return reply
        if not _session_ok(headers):
            return None
        if method == 'GET' and target == CHALLENGES and not body:
            return xml_response(challenges_xml(account))
        if method == 'GET' and target == REWARDS_TO_CLAIM and not body:
            recover(account)
            return xml_response(rewards_to_claim_xml(account))
        if method == 'GET' and target == PROGRESS + '?remotePersonaId=%d' % local_profile.load_profile().persona_id \
                and not body:
            recover(account)
            return xml_response(progress_xml(account))
        if method == 'POST' and target == DETAILS and body.startswith(b'<LongList '):
            ids = {int(x) for x in re.findall(rb'<array:long>(\d+)</array:long>', body)}
            return xml_response(details_xml(ids))
        match = re.fullmatch(re.escape(CLAIM) + r'\?rewardId=(\d{1,10})', target)
        if method == 'GET' and match and not body:
            return xml_response(claim(account, int(match.group(1))))
    except (ValueError, KeyError, TypeError, OSError):
        return None
    return None
