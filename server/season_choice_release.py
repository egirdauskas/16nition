"""Prospective admission of certified competition choices and difficulty rewards.

The existing native journal owns every transition. Admission adds configuration
only: the archived current cycle keeps its original reward mode until completion.
"""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REAL=ROOT/'server/data/development/fm16in2026'
MARKER='season-choice-release.json'
VERSION='local_season_choice_release_v1'
CONTRACT=ROOT/'reports/reward-difficulty/2026-10-29/choice-packs/certificate.json'
CONTRACT_SHA='19e94b68acdb6648da92e714298047c3dd4b327a97dab3ce8faf6d4107ef2a55'
POLICIES=tuple(ROOT/'server/policy'/n for n in
    ('offline-season-choices-v1.json','difficulty-rewards-v1.json','reward-store-parity-v1.json'))
ACCOUNT=POLICY=None

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def ordinary(path):
    path=Path(path)
    if path.is_symlink() or path.stat().st_nlink!=1:raise ValueError('Choice admission alias refused')
    return path

def marker(account,archive,certificate=None):
    account,archive=Path(account).resolve(),Path(archive).resolve()
    state=json.loads((archive/'native-seasons.json').read_bytes())
    if state['active_match'] or state['prepared']:raise ValueError('Quiescent choice admission required')
    modes={bool(s.get('difficulty_reward_start')) for s in state['matches'] if s['cycle_id']==state['cycle']['id']}
    if len(modes)>1:raise ValueError('Mixed historical reward modes refused')
    return dict(version=VERSION,account=str(account),phase='enabled' if certificate else 'candidate',
        origin_archive=str(archive),origin_manifest_sha256=sha(archive/'.lab-snapshot.json'),
        grandfathered_cycle_id=state['cycle']['id'],grandfathered_difficulty=next(iter(modes),False),
        native_contract_sha256=CONTRACT_SHA,policies={str(p):sha(p) for p in POLICIES},
        certificate=str(Path(certificate).resolve()) if certificate else None,
        certificate_sha256=sha(certificate) if certificate else None)

def validate(account):
    account=Path(account)
    if account.is_symlink():raise ValueError('Choice account alias refused')
    account=account.resolve()
    if account!=REAL and (ROOT/'reports' not in account.parents or account.name!='isolated-account'):
        raise ValueError('Choice admission account differs')
    value=json.loads(ordinary(account/MARKER).read_bytes())
    archive=Path(value['origin_archive'])
    if archive.is_symlink() or ROOT/'reports' not in archive.resolve().parents or archive.resolve()==account:
        raise ValueError('Separate choice admission archive required')
    manifest=ordinary(archive/'.lab-snapshot.json')
    if sha(manifest)!=value['origin_manifest_sha256']:raise ValueError('Choice archive manifest changed')
    files=json.loads(manifest.read_bytes())['sha256']
    if not {'profile.json','native-seasons.json','seasons.json','definition.json','packs.json','reward-release.json'}<=files.keys():
        raise ValueError('Incomplete choice admission archive')
    for name,digest in files.items():
        if Path(name).name!=name or sha(ordinary(archive/name))!=digest:raise ValueError('Choice archive changed')
    expected=marker(account,archive,value.get('certificate'))
    if value!=expected or sha(ordinary(CONTRACT))!=CONTRACT_SHA:raise ValueError('Choice admission contract/configuration changed')
    old=json.loads((archive/'profile.json').read_bytes());current=json.loads(ordinary(account/'profile.json').read_bytes())
    if any(old[k]!=current[k] for k in ('persona_id','identity_pid','user_id')):raise ValueError('Choice admission identity changed')
    if value['phase']=='candidate':
        if account==REAL:raise ValueError('Uncertified normal choice admission refused')
    else:
        path=Path(value['certificate'])
        if ROOT/'reports' not in path.resolve().parents:raise ValueError('Local choice certificate required')
        proof=json.loads(ordinary(path).read_bytes())
        required=('legacy_cycle_preserved','boundary_verified','choice_verified','difficulty_rewards_verified',
                  'store_preserved','restart_verified','exact_retry_verified')
        if proof.get('status')!='STOCK_VERIFIED_SEASON_CHOICE_RELEASE' or not all(proof.get(k) is True for k in required):
            raise ValueError('Incomplete normal choice certificate')
        if not proof.get('proof_files'):raise ValueError('Choice certificate evidence required')
        for name,digest in proof['proof_files'].items():
            file=ROOT/name
            if not any(p in file.resolve().parents for p in (ROOT/'reports',ROOT/'captures')) or sha(ordinary(file))!=digest:
                raise ValueError('Choice certificate evidence changed')
    return value

def configure(account=None):
    global ACCOUNT,POLICY
    ACCOUNT=POLICY=None
    if account is None:return
    from . import reward_release
    if not reward_release.selected(account) or not reward_release.compact_records(account):
        raise ValueError('Choices require certified compact reward/Store admission')
    value=validate(account)
    ACCOUNT=Path(account).resolve();POLICY=dict(value,marker_sha256=sha(ACCOUNT/MARKER))

def selected(account):
    from .fresh_account_runtime import selected as fresh_selected
    if fresh_selected(account):
        return True
    if ACCOUNT is None or Path(account).resolve()!=ACCOUNT:return False
    if sha(ACCOUNT/MARKER)!=POLICY['marker_sha256']:raise ValueError('Choice admission changed during runtime')
    return True

def difficulty_enabled(account,state):
    if not selected(account):raise ValueError('Choice admission not configured')
    from .fresh_account_runtime import selected as fresh_selected
    if fresh_selected(account):
        return state['cycle'].get('season_choice_selection') is not None
    if state['cycle']['id']==POLICY['grandfathered_cycle_id']:
        return POLICY['grandfathered_difficulty']
    return state['cycle'].get('season_choice_selection') is not None
