"""Certificate-backed admission of the offline Transfer Market (MARKET-001..006).

Mirrors tournament_release: the normal account runs the market only through a
hash-pinned marker naming a separate archived backup, the exact economy policy
and a certificate whose archived evidence is unchanged.
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / 'server/data/development/fm16in2026'
MARKER = 'market-release.json'
VERSION = 'market_release_v1'
STATUS = 'STOCK_VERIFIED_TRANSFER_MARKET_V1'
CERT_ROOT = ROOT / 'reports/market'
CHECKS = (
    'search_and_filters', 'card_status_wallet', 'buy_now', 'bid_hold_outbid_refund',
    'transfer_targets_states', 'add_to_watch_list', 'won_lost_claim_clear', 'price_limits',
    'listing_escrow', 'bot_sale_fee', 'clear_sold', 'expiry_relist', 'exact_retry_verified',
    'restart_verified', 'economy_user_accepted',
)
# MARKET-008 extension: same machinery, separate marker/certificate, selected by
# the economy policy version actually being enabled (v1 adds non-player items).
MARKER_V2 = 'market-release-v2.json'
VERSION_V2 = 'market_release_v2'
STATUS_V2 = 'STOCK_VERIFIED_TRANSFER_MARKET_V2'
CHECKS_V2 = CHECKS + (
    'item_search_categories', 'item_buy_now', 'manager_club_and_squad_swap', 'item_listing',
    'item_bot_sale_fee', 'coach_physio_empty', 'consumables_sell_only', 'sale_speed_underpricing',
)
MARKER_KEYS = {'version', 'account', 'archive', 'manifest_sha256', 'policy_sha256',
               'certificate', 'certificate_sha256'}


def sha(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_nlink != 1:
        raise ValueError('Market evidence alias refused')
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Policy v2: position-change and formation prices (pricing only; same contracts).
MARKER_V3 = 'market-release-v3.json'
VERSION_V3 = 'market_release_v3'
STATUS_V3 = 'STOCK_VERIFIED_TRANSFER_MARKET_V3'
CHECKS_V3 = CHECKS_V2 + ('position_formation_pricing_user_accepted',)


def edition(policy):
    """(marker, version, checks, status) for the economy policy being admitted."""
    version = json.loads(Path(policy).read_bytes()).get('version')
    if version == 'market_economy_v2':
        return MARKER_V3, VERSION_V3, CHECKS_V3, STATUS_V3
    if version == 'market_economy_v1':
        return MARKER_V2, VERSION_V2, CHECKS_V2, STATUS_V2
    return MARKER, VERSION, CHECKS, STATUS


def certificate(path, policy):
    path = Path(path).resolve()
    if CERT_ROOT not in path.parents:
        raise ValueError('Market certificate location differs')
    proof = json.loads(path.read_bytes())
    _, _, checks, status = edition(policy)
    if (proof.get('status') != status or proof.get('policy_sha256') != sha(policy)
            or any(proof.get(k) is not True for k in checks)
            or type(proof.get('evidence')) is not dict or not proof['evidence']):
        raise ValueError('Incomplete market certificate')
    for name, digest in proof['evidence'].items():
        item = Path(name)
        if item.is_absolute() or '..' in item.parts:
            raise ValueError('Invalid market evidence path')
        item = ROOT / item
        if ROOT / 'reports' not in item.parents and ROOT / 'captures' not in item.parents:
            raise ValueError('Market evidence must be archived')
        if sha(item) != digest:
            raise ValueError('Market evidence changed')
    return proof


def admit(account, policy):
    """Validate the normal account's market marker; ValueError if anything differs."""
    marker, version, _, _ = edition(policy)
    account = Path(account).resolve()
    path = account / marker
    if account != REAL or not path.is_file():
        raise ValueError('Uncertified market requires an archived isolated account')
    value = json.loads(path.read_bytes())
    if (set(value) != MARKER_KEYS or value['version'] != version or value['account'] != str(account)
            or value['policy_sha256'] != sha(policy)):
        raise ValueError('Invalid market release marker')
    archive = Path(value['archive']).resolve()
    if CERT_ROOT not in archive.parents or archive == account:
        raise ValueError('Separate market backup required')
    if sha(archive / '.lab-snapshot.json') != value['manifest_sha256']:
        raise ValueError('Market backup manifest changed')
    files = json.loads((archive / '.lab-snapshot.json').read_bytes())['sha256']
    if not {'profile.json', 'football.json', 'control.json'} <= files.keys():
        raise ValueError('Incomplete market backup')
    for name, digest in files.items():
        if Path(name).name != name or sha(archive / name) != digest:
            raise ValueError('Market backup changed')
    before, current = [json.loads((p / 'profile.json').read_bytes()) for p in (archive, account)]
    if any(before.get(k) != current.get(k) for k in ('persona_id', 'identity_pid', 'user_id')):
        raise ValueError('Market owner changed')
    if sha(value['certificate']) != value['certificate_sha256']:
        raise ValueError('Market certificate changed')
    certificate(value['certificate'], policy)
    return value
