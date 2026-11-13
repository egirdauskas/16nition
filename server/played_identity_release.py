"""Backed-up admission of the certified source-first played completion path.

Configuration only; NativeSeasonCoordinator owns every reward and recovery.
"""
import json
from pathlib import Path
from .sim_completion_release import ROOT,REAL,sha,ordinary_file,validate as validate_sim

MARKER='played-identity-release.json'
VERSION='local_played_identity_release_v1'
CONTRACT=ROOT/'reports/native-rewards/2026-10-24-played-identity-certification/stock-certificate.json'


def marker(account,archive):
    return {'version':VERSION,'account':str(Path(account).resolve()),'modes':['played'],
        'origin_archive':str(Path(archive).resolve()),
        'origin_manifest_sha256':sha(Path(archive)/'.lab-snapshot.json'),
        'certificate':str(CONTRACT),'certificate_sha256':sha(CONTRACT)}


def validate(account):
    account=Path(account)
    if account.is_symlink():raise ValueError('Played identity account alias refused')
    account=account.resolve()
    if account!=REAL and (ROOT/'reports' not in account.parents or account.name!='isolated-account'):
        raise ValueError('Played identity account differs')
    for path in account.glob('*.json'):ordinary_file(path)
    value=json.loads(ordinary_file(account/MARKER).read_bytes())
    if (set(value)!={'version','account','modes','origin_archive','origin_manifest_sha256','certificate','certificate_sha256'}
            or value['version']!=VERSION or value['account']!=str(account) or value['modes']!=['played']):
        raise ValueError('Invalid played identity release marker')
    origin=Path(value['origin_archive'])
    if origin.is_symlink():raise ValueError('Played identity archive alias refused')
    origin=origin.resolve()
    if ROOT/'reports' not in origin.parents or origin==account or account in origin.parents:
        raise ValueError('Separate played identity archive required')
    if sha(ordinary_file(origin/'.lab-snapshot.json'))!=value['origin_manifest_sha256']:
        raise ValueError('Played identity archive manifest changed')
    manifest=json.loads((origin/'.lab-snapshot.json').read_bytes())['sha256']
    if not {'profile.json','football.json','packs.json','purchases.json','native-seasons.json','control.json',
            'gameplay-release.json','atomic-match-release.json','played-match-release.json','sim-completion-release.json'}<=manifest.keys():
        raise ValueError('Incomplete played identity archive')
    for name,digest in manifest.items():
        if Path(name).name!=name or sha(ordinary_file(origin/name))!=digest:raise ValueError('Played identity archive changed')
    old=json.loads((origin/'profile.json').read_bytes());current=json.loads((account/'profile.json').read_bytes())
    if any(old[k]!=current[k] for k in ('persona_id','identity_pid','user_id')):
        raise ValueError('Played identity owner changed')
    from .store_release import configuration_preserved
    if (not configuration_preserved(account,origin) or
        sha(account/'sim-completion-release.json')!=sha(origin/'sim-completion-release.json')):
        raise ValueError('Played identity admission changed supported configuration')
    certificate=Path(value['certificate'])
    if certificate!=CONTRACT or sha(ordinary_file(certificate))!=value['certificate_sha256']:
        raise ValueError('Played identity certificate changed')
    proof=json.loads(certificate.read_bytes())
    if (proof.get('status')!='STOCK_VERIFIED_SOURCE_FIRST_PLAYED_COMPLETION'
            or proof.get('resolver')!='played_report_end_source'
            or not all(proof.get(k) is True for k in ('original_Awards_verified','original_save_verified',
                'restart_verified','exact_retry_verified','backend_identical_end_verified','backend_recovery_verified',
                'normal_preserved','store_preserved'))
            or proof.get('native_byte_identical_pair_claimed') is not False
            or proof.get('native_duplicate_callback_claimed') is not False
            or not all(type(proof.get(k)) is int and proof[k]>0 for k in ('native_capture','restart_capture'))
            or proof['native_capture']==proof['restart_capture'] or not proof.get('proof_files')):
        raise ValueError('Played source-first certificate incomplete')
    for name,digest in proof['proof_files'].items():
        path=ROOT/name
        if (not any(folder in path.resolve().parents for folder in (ROOT/'reports',ROOT/'captures'))
                or sha(ordinary_file(path))!=digest):raise ValueError('Played identity proof changed')
    validate_sim(account)
    return value
