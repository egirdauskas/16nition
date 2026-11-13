"""Original Club search/ActivateCard, explicitly admitted on one local account."""
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from .account_transaction import account_locked

ROOT = Path(__file__).resolve().parents[1]
MARKER = 'club-item-actions-release.json'
ACCOUNT = POLICY = None


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def configure(account=None):
    global ACCOUNT, POLICY
    ACCOUNT = POLICY = None
    if account is None:
        return
    account = Path(account).resolve()
    from .fresh_account_runtime import selected as fresh_selected
    if fresh_selected(account):
        ACCOUNT, POLICY = account, {
            'fresh_account': True, 'phase': 'fresh_profile',
            'features': ['search', 'activation', 'quick_sell', 'transfer_storage',
                         'unassigned_activation', 'club_rename'],
        }
        return
    path = account / MARKER
    if not path.exists():
        return
    value = json.loads(path.read_bytes())
    if (path.is_symlink() or set(value) != {'version', 'account', 'archive', 'manifest_sha256',
            'phase', 'features', 'certificate', 'certificate_sha256'} or
            value['version'] != 'club_item_actions_v1' or value['account'] != str(account) or
            type(value['features']) is not list or not value['features'] or
            value['features'] != sorted(set(value['features'])) or
            'search' not in value['features'] or
            set(value['features']) - {'search', 'activation', 'quick_sell', 'transfer_storage',
                                     'unassigned_activation', 'club_rename'}):
        raise ValueError('Unmapped club-item admission')
    archive = Path(value['archive']).resolve()
    if ROOT / 'reports' not in archive.parents or archive == account or sha(archive / '.lab-snapshot.json') != value['manifest_sha256']:
        raise ValueError('Separate club-item archive required')
    files = json.loads((archive / '.lab-snapshot.json').read_bytes())['sha256']
    if not {'profile.json', 'football.json'} <= files.keys():
        raise ValueError('Incomplete club-item archive')
    for name, digest in files.items():
        p = archive / name
        if Path(name).name != name or p.is_symlink() or sha(p) != digest:
            raise ValueError('Club-item archive changed')
    old, current = [json.loads((p / 'profile.json').read_bytes()) for p in (archive, account)]
    if any(old[k] != current[k] for k in ('persona_id', 'identity_pid', 'user_id')):
        raise ValueError('Club-item owner changed')
    if value['phase'] == 'candidate':
        if (ROOT / 'reports' not in account.parents or account.name != 'isolated-account' or
                not (account / '.lab-snapshot.json').is_file() or value['certificate'] is not None or
                value['certificate_sha256'] is not None):
            raise ValueError('Uncertified club-item actions are isolated-only')
    elif value['phase'] == 'enabled':
        from .store_release import REAL
        certificate = Path(value['certificate']).resolve()
        if (account != REAL or not any(p in certificate.parents for p in
                (ROOT / 'reports/consumable-application', ROOT / 'reports/club-release', ROOT / 'reports/club-ui')) or
                certificate.is_symlink() or sha(certificate) != value['certificate_sha256']):
            raise ValueError('Club-item certificate changed')
        proof = json.loads(certificate.read_bytes())
        if (proof.get('status') != 'STOCK_VERIFIED_CLUB_ITEM_ACTIONS' or proof.get('features') != value['features'] or
                not isinstance(proof.get('item_types'), list) or not proof['item_types'] or
                set(proof['item_types']) - {'badge', 'kit', 'stadium', 'ball'} or
                any(proof.get(k) is not True for k in ('original_ui', 'native_actives', 'old_active_retained',
                    'ownership_preserved', 'restart_verified', 'retry_verified'))):
            raise ValueError('Incomplete club-item certificate')
        for feature, key in (('quick_sell', 'club_transfer_quick_sell'),
                             ('transfer_storage', 'club_transfer_storage'),
                             ('unassigned_activation', 'unassigned_activation'),
                             ('club_rename', 'club_rename')):
            if feature in value['features'] and proof.get(key) is not True:
                raise ValueError('Incomplete inventory action certificate: '+feature)
        value['verified_item_types'] = proof['item_types']
    else:
        raise ValueError('Invalid club-item phase')
    ACCOUNT, POLICY = account, dict(value, marker_sha256=sha(path))


def selected(store):
    if ACCOUNT is None or store.path.resolve().parent != ACCOUNT:
        return False
    if POLICY.get('fresh_account'):
        from .fresh_account_runtime import selected as fresh_selected
        return fresh_selected(ACCOUNT)
    if sha(ACCOUNT / MARKER) != POLICY['marker_sha256']:
        raise ValueError('Club-item selector changed during runtime')
    return True


def activation_enabled(store):
    return selected(store) and 'activation' in POLICY['features']


def quick_sell_enabled(store):
    return selected(store) and 'quick_sell' in POLICY['features']


def transfer_storage_enabled(store):
    return selected(store) and 'transfer_storage' in POLICY['features']


def unassigned_activation_enabled(store):
    return selected(store) and 'unassigned_activation' in POLICY['features']


def rename_enabled(store):
    return selected(store) and 'club_rename' in POLICY['features']


@lru_cache(maxsize=1)
def kit_categories():
    from .local_content_source import DB, META, cards
    from scripts.local_football_db import FootballDB
    cards()
    db = FootballDB(DB, META)
    limit = db.table('fcc_kitcards')['valid_count']
    rows = {r['carddbid']: r['category'] for r in db.rows('fcc_kitcards', ['carddbid', 'category']) if r['row_index'] < limit}
    if any(v not in (2, 3) for v in rows.values()):
        raise ValueError('Unmapped supplied kit category')
    return rows


def category(item):
    """02180a00: badge100, home101, away102, stadium103, ball104."""
    from .local_football import OwnedBadgeItem
    if type(item) is OwnedBadgeItem or item.item_type == 'badge':
        return 100
    if item.item_type == 'kit':
        return 99 + kit_categories()[item.resource_id]
    return {'stadium': 103, 'ball': 104}[item.item_type]


def preview(state, source_id, *, unassigned=False):
    """One ownership-role swap, without allocation, retirement or wallet changes."""
    from dataclasses import replace
    from .local_football import OwnedBadgeItem, OwnedClubItem, ItemLocation, item_pile, owned_instance_ids
    active = list(state.active_club_items)
    if state.active_badge is not None:
        active.append(state.active_badge)
    source = next((i for i in (*active, *state.owned_club_items) if i.instance_id == source_id), None)
    if source is None or item_pile(state, source_id) not in (('club','unassigned') if unassigned else ('club',)):
        raise ValueError('Activation requires an owned Club item')
    slot = category(source)
    previous = [i for i in active if category(i) == slot]
    if len(previous) > 1:
        raise ValueError('Conflicting active club slot')
    if previous and previous[0].instance_id == source_id:
        return state, source
    inactive = [i for i in state.owned_club_items if i.instance_id != source_id]
    if previous:
        old = previous[0]
        inactive.append(OwnedClubItem(old.instance_id, old.resource_id, 'badge') if type(old) is OwnedBadgeItem else old)
    change = dict(owned_club_items=tuple(sorted(inactive, key=lambda i: i.instance_id)))
    if item_pile(state, source_id)=='unassigned':
        placements={i.instance_id:i for i in state.inventory_locations}
        for item in (source,*previous):placements[item.instance_id]=ItemLocation(item.instance_id,'club')
        change['inventory_locations']=tuple(sorted(placements.values(),key=lambda i:i.instance_id))
    if slot == 100:
        change['active_badge'] = OwnedBadgeItem(source.instance_id, source.resource_id)
    else:
        change['active_club_items'] = tuple(i for i in state.active_club_items if category(i) != slot) + (source,)
    updated = replace(state, **change)
    if owned_instance_ids(updated) != owned_instance_ids(state):
        raise ValueError('Activation changed total ownership')
    return updated, source


PREFIX = '/ut/game/fifaworldmobile/item/'


def decode(method, target, headers, body):
    from .game_auth import SID
    if (method != 'PUT' or not re.fullmatch(re.escape(PREFIX) + r'[1-9][0-9]*', target) or
            headers.get(b'host') != b'10.0.2.2:18081' or headers.get(b'x-ut-sid') != SID.encode() or
            headers.get(b'content-type') != b'application/json' or headers.get(b'content-length') != str(len(body)).encode() or
            json.loads(body) != {'itemState': 'active'}):
        raise ValueError('Not the captured authenticated ActivateCard request')
    iid = int(target[len(PREFIX):])
    if iid > 0x7fffffffffffffff:
        raise ValueError('Invalid activation identity')
    return iid


def guard_playing(store):
    path = store.path.with_name('native-seasons.json')
    active = json.loads(path.read_bytes()).get('active_match') if path.exists() else None
    if active and active.get('status') == 'playing':
        raise ValueError('Club equipment cannot change during an accepted playing match')


@account_locked
def response_for(method, target, headers, body, store):
    from .football_protocol import encode_owned_club_item
    from .identity import json_response
    from .local_football import OwnedBadgeItem, OwnedClubItem, validate
    if target=='/ut/game/fifaworldmobile/user/club':
        from .club_name import response_for as rename_response
        return rename_response(method,target,headers,body,store)
    if not activation_enabled(store):
        return None
    try:
        iid = decode(method, target, headers, body)
        before = store.load(1)
        updated, source = preview(before, iid, unassigned=unassigned_activation_enabled(store))
        if updated != before:
            guard_playing(store)
        validate(updated, store.catalog)
        if type(source) is OwnedBadgeItem:
            source = OwnedClubItem(source.instance_id, source.resource_id, 'badge')
        if POLICY is not None and POLICY['phase'] == 'enabled' and source.item_type not in POLICY['verified_item_types']:
            raise ValueError('Uncertified club-item family')
        # Selector12 uses the shared owned-item decoder.02180dc4 changes the
        # cached active reference using its retained owned ID/category after
        # successful status; no invented active-state field is needed.
        return json_response({'itemData': [encode_owned_club_item(source, store.path.parent)]})
    except (ValueError, TypeError, KeyError, UnicodeError):
        return None


@account_locked
def commit_request(method, target, headers, body, store):
    if target=='/ut/game/fifaworldmobile/user/club':
        from .club_name import commit_request as rename_commit
        return rename_commit(method,target,headers,body,store)
    if not activation_enabled(store) or method != 'PUT' or not target.startswith(PREFIX):
        return None
    iid = decode(method, target, headers, body)
    with store.transaction():
        if response_for(method, target, headers, body, store) is None:
            raise ValueError('Invalid owned club activation')
        before = store.load(1)
        after, _ = preview(before, iid, unassigned=unassigned_activation_enabled(store))
        if after != before:
            store.save(after)
        return response_for(method, target, headers, body, store)


def search(query, store):
    """Original ClubSearch kinds/tiers, sharing the captured paging contract."""
    from .club_player_search import integer
    from .football_protocol import encode_owned_club_item
    from .identity import json_response
    from .local_football import OwnedClubItem, item_pile
    kinds = {'equippables': None, 'badge': 'badge', 'kit': 'kit', 'stadium': 'stadium', 'ball': 'ball'}
    if not selected(store) or len(query.get('type', [])) != 1 or query['type'][0] not in kinds:
        return None
    if (set(query) not in ({'type', 'level', 'count'}, {'type', 'level', 'count', 'start'}) or
            any(len(v) != 1 for v in query.values()) or query['level'][0] not in ('any', 'bronze', 'silver', 'gold')):
        return None
    count = integer(query['count'][0], 1, 0x7fffffff)
    start = integer(query.get('start', ['0'])[0], 0, 0x7fffffff)
    state = store.load(1)
    items = list(state.owned_club_items) + list(state.active_club_items)
    if state.active_badge is not None:
        badge = state.active_badge
        items.append(OwnedClubItem(badge.instance_id, badge.resource_id, 'badge'))
    from .local_club_items import reference, quality
    kind = kinds[query['type'][0]]
    if kind is not None:
        items = [i for i in items if i.item_type == kind]
    level = query['level'][0]
    if level != 'any':
        items = [i for i in items if quality(reference(i.item_type, i.resource_id)) == level]
    items = sorted((i for i in items if item_pile(state, i.instance_id) == 'club'), key=lambda i: i.instance_id)
    return json_response({'itemData': [encode_owned_club_item(i, store.path.parent) for i in items[start:start + count]]})
