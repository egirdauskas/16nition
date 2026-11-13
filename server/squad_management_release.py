"""Configuration-only admission of the physically tested squad workflows."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = 'squad-management-release.json'
FEATURES = ['player_search', 'manager_picker', 'squad_edit', 'squad_names',
            'squad_build', 'squad_copy', 'squad_select', 'inactive_squad_delete']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(account):
    account = Path(account)
    if account.is_symlink(): raise ValueError('Squad account alias refused')
    account = account.resolve()
    marker = account/MARKER
    if marker.is_symlink() or marker.stat().st_nlink != 1: raise ValueError('Squad selector alias refused')
    value = json.loads(marker.read_bytes())
    if (set(value) != {'version', 'account', 'origin_archive', 'origin_manifest_sha256',
                      'certificate', 'certificate_sha256'} or
            value['version'] != 'local_squad_management_release_v1' or value['account'] != str(account)):
        raise ValueError('Squad admission differs')
    origin = Path(value['origin_archive']).resolve()
    cert = Path(value['certificate']).resolve()
    if ROOT/'reports' not in origin.parents or ROOT/'reports' not in cert.parents or origin == account:
        raise ValueError('Separate squad archive and certificate required')
    if sha(origin/'.lab-snapshot.json') != value['origin_manifest_sha256']:
        raise ValueError('Squad archive manifest changed')
    manifest = json.loads((origin/'.lab-snapshot.json').read_bytes())['sha256']
    if not {'football.json', 'profile.json', 'control.json'} <= manifest.keys():
        raise ValueError('Incomplete squad archive')
    for name, digest in manifest.items():
        path = origin/name
        if Path(name).name != name or path.is_symlink() or sha(path) != digest:
            raise ValueError('Squad archive changed')
    if cert.is_symlink() or sha(cert) != value['certificate_sha256']:
        raise ValueError('Squad certificate changed')
    proof = json.loads(cert.read_bytes())
    if (proof.get('status') != 'STOCK_VERIFIED_SQUAD_WORKFLOWS' or proof.get('features') != FEATURES or
            not proof.get('restart_verified') or not proof.get('backend_retry_verified') or
            not proof.get('proof_files')):
        raise ValueError('Squad certificate incomplete')
    for name, digest in proof['proof_files'].items():
        path = ROOT/name
        if (path.is_symlink() or not any(root in path.resolve().parents for root in (ROOT/'reports', ROOT/'captures')) or
                sha(path) != digest): raise ValueError('Squad proof changed')
    return value
