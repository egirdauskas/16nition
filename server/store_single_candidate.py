"""Archived catalog override on the existing certified Store.

Parent release validation still checks its original catalog/configuration.
Only the prospective product list changes; ownership and journals are shared.
The isolated candidate selector cannot admit the normal account; the real
account needs the deployment selector bound to a native certificate.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = 'store-single-candidate.json'
_MARKER_CACHE = {}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


FIELDS = {
    'version', 'account', 'archive', 'manifest_sha256',
    'products_sha256', 'price_policy_sha256', 'caption_profile_sha256',
    'text_policy_sha256',
}
DEPLOYMENT = 'store_single_deployment_v1'
CERTIFIED = 'STOCK_VERIFIED_SINGLE_CONSUMABLES_DIRECT'
CLAIMS = (
    'purchase_verified', 'direct_delivery_verified', 'storage_verified',
    'restart_verified', 'exact_retry_verified', 'all_categories_verified',
    'legacy_captions_preserved',
)


def _marker(raw):
    digest = hashlib.sha256(raw).digest()
    if digest in _MARKER_CACHE:
        return _MARKER_CACHE[digest]
    value = json.loads(raw)
    expected = {
        'store_single_candidate_v1': FIELDS,
        DEPLOYMENT: FIELDS | {'certificate', 'certificate_sha256'},
    }
    if (
        type(value) is not dict or value.get('version') not in expected
        or set(value) != expected[value['version']]
        or any(type(v) is not str or not v for v in value.values())
    ):
        raise ValueError('Invalid single-consumable Store selector')
    if len(_MARKER_CACHE) >= 8:
        _MARKER_CACHE.clear()
    _MARKER_CACHE[digest] = value
    return value


def certificate(value):
    """Native certificate required to deploy on the real account."""
    path = Path(value['certificate']).resolve()
    if (
        ROOT / 'reports/store-release' not in path.parents or path.is_symlink()
        or sha(path) != value['certificate_sha256']
    ):
        raise ValueError('Single-card Store certificate changed')
    proof = json.loads(path.read_bytes())
    if proof.get('status') != CERTIFIED or any(proof.get(k) is not True for k in CLAIMS):
        raise ValueError('Single-card Store certificate incomplete')
    return proof


def selection(account):
    account = Path(account).resolve()
    marker = account / MARKER
    if not marker.exists():
        return None
    from .store_release import REAL
    deployed = account == REAL
    if marker.is_symlink() or (not deployed and (
        ROOT / 'reports' not in account.parents or account.name != 'isolated-account'
        or not (account / '.lab-snapshot.json').is_file()
    )):
        raise ValueError('Individual Store candidates require a separate archived account')
    value = deepcopy(_marker(marker.read_bytes()))
    if value['account'] != str(account):
        raise ValueError('Individual Store candidate owner selector differs')
    if deployed != (value['version'] == DEPLOYMENT):
        raise ValueError('Only a certified deployment selector may select the real account')
    if deployed:
        certificate(value)
    from .store_release import archive, MARKER as store_marker
    backup = archive(value['archive'], value['manifest_sha256'])
    if backup == account or account in backup.parents:
        raise ValueError('Separate single-consumable migration archive required')
    from .store_single_consumables import PATH as price_path, catalog
    from .store_single_caption_bank import PATH as caption_path, bank
    from .store_single_captions import PATH as text_path
    if (
        sha(price_path) != value['price_policy_sha256']
        or sha(caption_path) != value['caption_profile_sha256']
        or sha(text_path) != value['text_policy_sha256']
        or sha(account / 'products.json') != value['products_sha256']
    ):
        raise ValueError('Single-consumable policy or catalog changed')
    from .pack_family_split import catalog as previous_catalog
    previous = json.loads((backup / 'products.json').read_bytes())
    if previous != previous_catalog():
        raise ValueError('Current certified sixteen-product Store must be archived first')
    if json.loads((account / 'products.json').read_bytes()) != catalog():
        raise ValueError('Only the approved specific-card Store candidates are allowed')
    for name in (store_marker, 'native-paid-pack-presentation.json'):
        if (account / name).read_bytes() != (backup / name).read_bytes():
            raise ValueError('Single-card candidate changed parent Store configuration')
    before = json.loads((backup / 'profile.json').read_bytes())
    current = json.loads((account / 'profile.json').read_bytes())
    if any(before[k] != current[k] for k in ('persona_id', 'identity_pid', 'user_id')):
        raise ValueError('Single-card candidate account identity changed')
    for name in ('packs.json', 'purchases.json', 'native-seasons.json'):
        path = backup / name
        if path.exists():
            old = json.loads(path.read_bytes())
            if old.get('prepared') or old.get('active_match'):
                raise ValueError('Single-card candidate requires a quiescent archive')
    session_name = 'pack-session-release.json' if deployed else 'pack-session-candidate.json'
    session = json.loads((account / session_name).read_bytes())
    if session.get('bank') != bank() or session.get('account') != str(account):
        raise ValueError('Specific-card Store requires the preserved append-only caption bank')
    return {'archive': backup, 'base_products': previous, 'selector': value}
