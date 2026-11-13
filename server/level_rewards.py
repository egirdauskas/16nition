"""Level-up rewards (XP-004, explicit revival_policy approved 5 November 2026).

Reaching level L pays ``coins_per_level * L`` coins; milestone levels also grant
one untradeable pack. Only level-ups earned after selection pay (no back pay):
a match pins ``start()`` at creation and its reward is a pure function of that
snapshot plus the XP the match earned, so retries, restarts and crash recovery
recompute identical values.

Stock evidence: the original post-match report reply's LevelUpInfo carries
CoinReward, CurrentLevel, PreviousLevel and RewardPackIds (decoder table
00329a34; reports/native-xp-level/decoded-match-reward-members-exact.json).
The LevelUp screen shows the coin number; packs go to Unopened Packs through
the existing source-grant journal.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import uuid

PATH = Path(__file__).parent / 'policy/level-rewards-v1.json'
VERSION = 'level_rewards_v1'
MARKER = 'level-rewards.json'
SOURCE_KIND = 'level'
_POLICY_CACHE = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validated_policy(raw):
    value = json.loads(raw)
    keys = {'version', 'classification', 'approved', 'default_enabled', 'coins_per_level',
            'milestone_packs', 'repeat_from_level', 'repeat_every_levels', 'repeat_pack'}
    if (type(value) is not dict or set(value) != keys or value['version'] != VERSION
            or value['classification'] != 'revival_policy' or value['default_enabled'] is not False
            or type(value['coins_per_level']) is not int or value['coins_per_level'] <= 0
            or type(value['milestone_packs']) is not dict
            or type(value['repeat_from_level']) is not int or value['repeat_from_level'] < 2
            or type(value['repeat_every_levels']) is not int or value['repeat_every_levels'] < 1):
        raise ValueError('Invalid level reward policy')
    from .reward_store_parity import policy as parity
    allowed = {b['definition'] for b in parity()['bindings'].values()}
    for level, definition in value['milestone_packs'].items():
        if not level.isdigit() or int(level) < 2 or definition not in allowed:
            raise ValueError('Level milestone must name an existing untradeable reward pack')
    if value['repeat_pack'] not in allowed:
        raise ValueError('Repeating level pack must be an existing untradeable reward pack')
    return value


def policy(path=PATH):
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).digest()
    if digest not in _POLICY_CACHE:
        _POLICY_CACHE[digest] = _validated_policy(raw)
    return deepcopy(_POLICY_CACHE[digest])


def allowed_pack_definitions():
    value = policy()
    return set(value['milestone_packs'].values()) | {value['repeat_pack']}


def pack_for(level, value=None):
    value = value or policy()
    if str(level) in value['milestone_packs']:
        return value['milestone_packs'][str(level)]
    first = value['repeat_from_level']
    if level >= first and (level - first) % value['repeat_every_levels'] == 0:
        return value['repeat_pack']
    return None


def enabled(account):
    """Per-account selector file; absent means level-ups pay nothing."""
    account = Path(account).resolve()
    marker = account / MARKER
    if not marker.exists():
        return False
    if marker.is_symlink():
        raise ValueError('Level reward selector must be a regular file')
    value = json.loads(marker.read_bytes())
    if (type(value) is not dict or set(value) != {'version', 'account', 'policy_sha256'}
            or value['version'] != VERSION):
        raise ValueError('Invalid level reward selector')
    if value['account'] != str(account):
        return False   # copied from another account: inactive here
    if value['policy_sha256'] != sha(PATH):
        raise ValueError('Level reward policy changed after selection')
    return True


def marker_for(account):
    policy()
    return {'version': VERSION, 'account': str(Path(account).resolve()), 'policy_sha256': sha(PATH)}


def start():
    """Prospective snapshot pinned when a match is created."""
    policy()
    return {'version': VERSION, 'policy_sha256': sha(PATH)}


def validate_start(value):
    if type(value) is not dict or value != start():
        raise ValueError('Invalid or changed level reward snapshot')


def quote(snapshot, before_level, after_level):
    """Coins and packs for every level crossed; empty when no level is gained."""
    validate_start(snapshot)
    if (type(before_level) is not int or type(after_level) is not int
            or before_level < 1 or after_level < before_level):
        raise ValueError('Invalid level crossing')
    value = policy()
    levels = list(range(before_level + 1, after_level + 1))
    packs = [{'level': n, 'definition': d} for n in levels if (d := pack_for(n, value))]
    from .local_profile import validate_credits
    coins = validate_credits(sum(value['coins_per_level'] * n for n in levels))
    return {'version': VERSION, 'policy_sha256': snapshot['policy_sha256'],
            'previous_level': before_level, 'current_level': after_level,
            'levels': levels, 'coins': coins, 'packs': packs}


def level_up_xml(calculation):
    """LevelUpInfo children in the original member order."""
    return f'<CoinReward>{calculation["coins"]}</CoinReward>' if calculation['coins'] else ''


def pack_receipt(owner_id, level, *, account_id, persona_id, cycle_id):
    source = uuid.uuid5(uuid.UUID(owner_id), f'level-{level}')
    return {'reward_id': str(uuid.uuid5(source, 'level-pack')), 'source_id': str(source),
            'source_kind': SOURCE_KIND, 'account_id': account_id, 'persona_id': persona_id,
            'cycle_id': cycle_id, 'policy_version': VERSION, 'certification': 'backend_only'}


def grant_images(calculation, profile_raw, packs_raw, *, owner_id, account_id, persona_id, cycle_id, encode):
    """Profile and PackStore images after paying one calculation."""
    from .local_packs import PackStore
    from .local_profile import validate_credits
    profile = json.loads(profile_raw)
    before = profile['credits']
    profile['credits'] = validate_credits(before + calculation['coins'])
    packs = json.loads(packs_raw)
    grants = []
    for row in calculation['packs']:
        receipt = pack_receipt(owner_id, row['level'], account_id=account_id,
                               persona_id=persona_id, cycle_id=cycle_id)
        packs, grant = PackStore.source_grant_image(packs, row['definition'], receipt)
        grants.append(grant)
    record = {'quote': calculation, 'credits_before': before, 'credits_after': profile['credits'],
              'grants': grants}
    return encode(profile), encode(packs), record
