"""Certificate-backed configuration for the original local Player Exchange UI."""
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REAL=ROOT/'server/data/development/fm16in2026'
MARKER='player-exchange-release.json'
CHECKS=('original_ui','free_retry_verified','confirmation_verified','storage_verified',
        'restart_verified','exact_retry_verified','source_retirement','unrelated_preserved',
        'rare_gold_backend_verified')


def sha(path):
    path=Path(path)
    if path.is_symlink() or path.stat().st_nlink!=1:raise ValueError('Exchange evidence alias refused')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def certificate(path,policy_path):
    path=Path(path).resolve()
    if ROOT/'reports/player-exchanges' not in path.parents:raise ValueError('Exchange certificate location differs')
    proof=json.loads(path.read_bytes())
    if (proof.get('status')!='STOCK_VERIFIED_PLAYER_EXCHANGES' or
            proof.get('policy_sha256')!=sha(policy_path) or
            any(proof.get(k) is not True for k in CHECKS) or
            type(proof.get('evidence')) is not dict or not proof['evidence']):
        raise ValueError('Incomplete exchange certificate')
    for name,digest in proof['evidence'].items():
        item=Path(name)
        if item.is_absolute() or '..' in item.parts:raise ValueError('Invalid exchange evidence path')
        item=ROOT/item
        if ROOT/'reports' not in item.parents and ROOT/'captures' not in item.parents:
            raise ValueError('Exchange evidence must be archived')
        if sha(item)!=digest:raise ValueError('Exchange evidence changed')
    return proof


def admit(account,policy_path):
    account=Path(account).resolve();path=account/MARKER
    if account!=REAL:raise ValueError('Uncertified player exchanges require an archived isolated account')
    if not path.is_file():raise ValueError('Uncertified player exchanges require an archived isolated account')
    value=json.loads(path.read_bytes())
    if (set(value)!={'version','account','archive','manifest_sha256','policy_sha256','certificate','certificate_sha256'} or
            value['version']!='player_exchange_release_v1' or value['account']!=str(account) or
            value['policy_sha256']!=sha(policy_path)):
        raise ValueError('Invalid exchange release marker')
    sha(path)
    archive=Path(value['archive']).resolve()
    if (ROOT/'reports/player-exchanges' not in archive.parents or archive==account or
            sha(archive/'.lab-snapshot.json')!=value['manifest_sha256']):raise ValueError('Separate exchange backup required')
    files=json.loads((archive/'.lab-snapshot.json').read_bytes())['sha256']
    if not {'profile.json','football.json','packs.json','purchases.json'}<=files.keys():raise ValueError('Incomplete exchange backup')
    for name,digest in files.items():
        if Path(name).name!=name or sha(archive/name)!=digest:raise ValueError('Exchange backup changed')
    before,current=[json.loads((p/'profile.json').read_bytes()) for p in (archive,account)]
    if any(before[k]!=current[k] for k in ('persona_id','identity_pid','user_id')):raise ValueError('Exchange owner changed')
    if sha(value['certificate'])!=value['certificate_sha256']:raise ValueError('Exchange certificate changed')
    certificate(value['certificate'],policy_path)
    return value
