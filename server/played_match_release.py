"""Backed-up admission of played/Sim coexistence; no financial state writes."""
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REAL=ROOT/'server/data/development/fm16in2026'
MARKER='played-match-release.json'
VERSION='local_played_match_release_v1'
CONTRACT=ROOT/'reports/native-xp-level/2026-10-22-played-integration/certificate.json'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def marker(account,archive,certificate=None):
    account=Path(account).resolve();archive=Path(archive).resolve()
    certificate=Path(certificate).resolve() if certificate else None
    return {'version':VERSION,'account':str(account),'phase':'enabled' if certificate else 'candidate',
        'origin_archive':str(archive),'origin_manifest_sha256':sha(archive/'.lab-snapshot.json'),
        'played_contract':str(CONTRACT),'played_contract_sha256':sha(CONTRACT),
        'certificate':str(certificate) if certificate else None,
        'certificate_sha256':sha(certificate) if certificate else None}

def validate(account):
    if Path(account).is_symlink():raise ValueError('Played account alias refused')
    account=Path(account).resolve()
    if account!=REAL and (ROOT/'reports' not in account.parents or account.name!='isolated-account'):
        raise ValueError('Played release account differs')
    for path in account.glob('*.json'):
        if path.is_symlink() or path.stat().st_nlink!=1:raise ValueError('Played account alias refused')
    value=json.loads((account/MARKER).read_bytes())
    if (set(value)!={'version','account','phase','origin_archive','origin_manifest_sha256','played_contract','played_contract_sha256','certificate','certificate_sha256'}
        or value['version']!=VERSION or value['account']!=str(account) or value['phase'] not in ('candidate','enabled')):
        raise ValueError('Invalid played deployment marker')
    archive=Path(value['origin_archive'])
    if archive.is_symlink():raise ValueError('Played archive alias refused')
    archive=archive.resolve()
    if ROOT/'reports' not in archive.parents or archive==account or account in archive.parents:
        raise ValueError('Separate played deployment archive required')
    if sha(archive/'.lab-snapshot.json')!=value['origin_manifest_sha256']:raise ValueError('Played archive changed')
    manifest=json.loads((archive/'.lab-snapshot.json').read_bytes())['sha256']
    if not {'profile.json','football.json','content.json','packs.json','purchases.json','products.json','seasons.json','definition.json','control.json','gameplay-release.json','atomic-match-release.json'}<=manifest.keys():
        raise ValueError('Incomplete played deployment archive')
    for name,digest in manifest.items():
        path=archive/name
        if Path(name).name!=name or path.is_symlink() or path.stat().st_nlink!=1 or sha(path)!=digest:
            raise ValueError('Played archive changed')
    old=json.loads((archive/'profile.json').read_bytes());current=json.loads((account/'profile.json').read_bytes())
    if any(old[k]!=current[k] for k in ('persona_id','identity_pid','user_id')):raise ValueError('Played deployment identity changed')
    from .store_release import configuration_preserved
    if not configuration_preserved(account,archive):raise ValueError('Played admission changed Store configuration')
    if Path(value['played_contract'])!=CONTRACT or sha(CONTRACT)!=value['played_contract_sha256']:
        raise ValueError('Played native contract changed')
    contract=json.loads(CONTRACT.read_bytes())
    if contract.get('status')!='STOCK_VERIFIED_PLAYED_XP' or not contract.get('restart_capture') or contract.get('exact_HTTP_retries',0)<1:
        raise ValueError('Played native contract incomplete')
    if value['phase']=='candidate':
        if account==REAL or value['certificate'] is not None or value['certificate_sha256'] is not None:
            raise ValueError('Uncertified normal played deployment refused')
    else:
        if type(value['certificate']) is not str:raise ValueError('Played composition certificate required')
        cert=Path(value['certificate'])
        if cert.is_symlink() or ROOT/'reports' not in cert.resolve().parents or sha(cert)!=value['certificate_sha256']:
            raise ValueError('Played composition certificate changed')
        proof=json.loads(cert.read_bytes())
        if (proof.get('status')!='STOCK_VERIFIED_MIXED_MATCHES' or proof.get('modes')!=['played','sim']
            or not all(proof.get(k) is True for k in ('restart_verified','exact_retry_verified','store_preserved'))
            or any(type(proof.get(k)) is not int or proof[k]<=0 for k in ('played_capture','sim_capture'))
            or proof['played_capture']==proof['sim_capture']):
            raise ValueError('Played composition certificate incomplete')
    return value
