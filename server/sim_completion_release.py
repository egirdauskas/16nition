"""Configuration-only admission of certified report-bound Sim completions.

NativeSeasonCoordinator remains the only source/reward/recovery journal.
Played equal-End handling is deliberately refused by that coordinator.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT/'server/data/development/fm16in2026'
MARKER = 'sim-completion-release.json'
VERSION = 'local_sim_completion_release_v1'
PROOF_ROOT = ROOT/'reports/gameplay-sampling/2026-10-24-season-outcomes/resume-20261024-1218/second-independent-club'
CONTRACT = PROOF_ROOT/'completion-identity-certificate.json'
CONTRACT_SHA = '060dd97953f628a0d3759dca32d7a59df3127b2f6b98bd58e4a9aba86a6b7a84'
EVIDENCE = PROOF_ROOT/'completion-identity-evidence-hashes.json'
EVIDENCE_SHA = 'a848913fa79e2a60a02dc41af3c8e70adb7fa0059b94c083c868f2d44fb6b3df'
CONFIG = ('products.json', 'store-release.json', 'native-paid-pack-presentation.json')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ordinary_file(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_nlink != 1:
        raise ValueError('Sim completion evidence/account alias refused')
    return path


def marker(account, archive, certificate=None):
    account = Path(account).resolve(); archive = Path(archive).resolve()
    certificate = Path(certificate).resolve() if certificate else None
    return {'version': VERSION, 'account': str(account), 'modes': ['sim'],
            'phase': 'enabled' if certificate else 'candidate',
            'origin_archive': str(archive), 'origin_manifest_sha256': sha(archive/'.lab-snapshot.json'),
            'native_contract_sha256': CONTRACT_SHA, 'native_evidence_sha256': EVIDENCE_SHA,
            'certificate': str(certificate) if certificate else None,
            'certificate_sha256': sha(certificate) if certificate else None}


def validate(account):
    account = Path(account)
    if account.is_symlink(): raise ValueError('Sim completion account alias refused')
    account = account.resolve()
    if account != REAL and (ROOT/'reports' not in account.parents or account.name != 'isolated-account'):
        raise ValueError('Sim completion account differs')
    for path in account.glob('*.json'): ordinary_file(path)
    value = json.loads(ordinary_file(account/MARKER).read_bytes())
    if (set(value) != {'version','account','modes','phase','origin_archive','origin_manifest_sha256',
                       'native_contract_sha256','native_evidence_sha256','certificate','certificate_sha256'}
            or value['version'] != VERSION or value['account'] != str(account)
            or value['modes'] != ['sim'] or value['phase'] not in ('candidate','enabled')):
        raise ValueError('Invalid Sim-only completion admission')
    archive = Path(value['origin_archive'])
    if archive.is_symlink(): raise ValueError('Sim completion archive alias refused')
    archive = archive.resolve()
    if ROOT/'reports' not in archive.parents or archive == account or account in archive.parents:
        raise ValueError('Separate Sim completion archive required')
    manifest = ordinary_file(archive/'.lab-snapshot.json')
    if sha(manifest) != value['origin_manifest_sha256']: raise ValueError('Sim completion archive manifest changed')
    files = json.loads(manifest.read_bytes())['sha256']
    if not {'profile.json','football.json','content.json','packs.json','purchases.json','products.json',
            'native-seasons.json','seasons.json','definition.json','control.json',
            'gameplay-release.json','atomic-match-release.json','store-release.json'} <= files.keys():
        raise ValueError('Incomplete Sim completion archive')
    for name, digest in files.items():
        if Path(name).name != name or sha(ordinary_file(archive/name)) != digest:
            raise ValueError('Sim completion archive changed')
    old = json.loads((archive/'profile.json').read_bytes())
    current = json.loads((account/'profile.json').read_bytes())
    if any(old[k] != current[k] for k in ('persona_id','identity_pid','user_id')):
        raise ValueError('Sim completion identity changed')
    from .store_release import configuration_preserved
    if not configuration_preserved(account,archive):
        raise ValueError('Sim completion admission changed Store configuration')
    if (value['native_contract_sha256'] != CONTRACT_SHA or sha(ordinary_file(CONTRACT)) != CONTRACT_SHA
            or value['native_evidence_sha256'] != EVIDENCE_SHA or sha(ordinary_file(EVIDENCE)) != EVIDENCE_SHA):
        raise ValueError('Certified Sim completion contract changed')
    if value['phase'] == 'candidate':
        if account == REAL or value['certificate'] is not None or value['certificate_sha256'] is not None:
            raise ValueError('Uncertified normal Sim completion admission refused')
    else:
        if type(value['certificate']) is not str: raise ValueError('Sim completion composition certificate required')
        certificate = Path(value['certificate'])
        if (certificate.is_symlink() or ROOT/'reports' not in certificate.resolve().parents
                or sha(ordinary_file(certificate)) != value['certificate_sha256']):
            raise ValueError('Sim completion composition certificate changed')
        proof = json.loads(certificate.read_bytes())
        if (proof.get('status') != 'STOCK_VERIFIED_SIM_COMPLETION_RELEASE' or proof.get('modes') != ['sim']
                or proof.get('native_contract_sha256') != CONTRACT_SHA
                or not all(proof.get(k) is True for k in ('restart_verified','exact_retry_verified',
                                                        'store_preserved','normal_preserved','played_equal_end_refused'))
                or not all(type(proof.get(k)) is int and proof[k] > 0 for k in ('native_capture','restart_capture'))
                or proof['native_capture'] == proof['restart_capture'] or not proof.get('proof_files')):
            raise ValueError('Sim completion composition certificate incomplete')
        for name, digest in proof['proof_files'].items():
            path = ROOT/name
            if (not any(root in path.resolve().parents for root in (ROOT/'reports',ROOT/'captures'))
                    or sha(ordinary_file(path)) != digest):
                raise ValueError('Sim completion composition evidence changed')
    return value
