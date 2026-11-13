"""Explicit backed-up admission of certified local gameplay beside the Store.

Configuration only. NativeSeasonCoordinator remains the sole reward journal.
A reports-only candidate can certify composition before real-account activation.
"""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REAL=ROOT/'server/data/development/fm16in2026'
MARKER='gameplay-release.json'
ACCOUNT=None
MARKER_SHA=None
FEATURES=['sim_xp','sim_match_coins','store']

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def validate(account):
    account=Path(account).resolve()
    if account!=REAL and (ROOT/'reports' not in account.parents or account.name!='isolated-account'):raise ValueError('Gameplay release account differs')
    for path in account.glob('*.json'):
        if path.is_symlink() or path.stat().st_nlink!=1:raise ValueError('Gameplay account alias refused')
        original=REAL/path.name
        if account!=REAL and original.exists() and path.samefile(original):raise ValueError('Real gameplay alias refused')
    p=json.loads((account/MARKER).read_bytes())
    required={'version','account','phase','origin_archive','origin_manifest_sha256','features','coin_policy_sha256','xp_policy_sha256','certificate','certificate_sha256'}
    if (set(p)!=required or p['version']!='local_gameplay_release_v1' or p['account']!=str(account) or
        p['phase'] not in ('candidate','enabled') or p['features']!=FEATURES):raise ValueError('Invalid gameplay release marker')
    origin=Path(p['origin_archive']).resolve()
    if ROOT/'reports' not in origin.parents or origin==account or account in origin.parents:raise ValueError('Separate gameplay archive required')
    if sha(origin/'.lab-snapshot.json')!=p['origin_manifest_sha256']:raise ValueError('Gameplay archive manifest changed')
    manifest=json.loads((origin/'.lab-snapshot.json').read_bytes())['sha256']
    required_files={'profile.json','football.json','content.json','packs.json','products.json','purchases.json','seasons.json','definition.json','control.json','store-release.json'}
    if not required_files<=manifest.keys():raise ValueError('Incomplete gameplay/Store archive')
    for name,expected in manifest.items():
        path=origin/name
        if Path(name).name!=name or path.is_symlink() or path.stat().st_nlink!=1 or sha(path)!=expected:raise ValueError('Gameplay archive changed')
    before=json.loads((origin/'profile.json').read_bytes());current=json.loads((account/'profile.json').read_bytes())
    if any(current[k]!=before[k] for k in ('persona_id','identity_pid','user_id')):raise ValueError('Gameplay identity changed')
    from .store_release import configuration_preserved
    if not configuration_preserved(account,origin):raise ValueError('Gameplay activation changed Store configuration')
    if p['coin_policy_sha256']!=sha(ROOT/'server/policy/native-match-coins.json') or p['xp_policy_sha256']!=sha(ROOT/'server/policy/account-progression.json'):raise ValueError('Gameplay approved policy changed')
    if p['phase']=='candidate':
        if account==REAL or p['certificate'] is not None or p['certificate_sha256'] is not None:raise ValueError('Uncertified real gameplay activation refused')
    else:
        if type(p['certificate']) is not str or type(p['certificate_sha256']) is not str:raise ValueError('Gameplay composition certificate required')
        cert=Path(p['certificate']).resolve()
        if ROOT/'reports' not in cert.parents or cert.is_symlink() or sha(cert)!=p['certificate_sha256']:raise ValueError('Gameplay certificate changed')
        proof=json.loads(cert.read_bytes())
        if (proof.get('status')!='STOCK_VERIFIED_COMBINED_XP_COINS_STORE' or proof.get('features')!=FEATURES or
            not proof.get('restart_verified') or not proof.get('exact_retry_verified') or not proof.get('native_capture')):raise ValueError('Gameplay composition certificate incomplete')
    return p

def configure(account=None):
    global ACCOUNT,MARKER_SHA
    ACCOUNT=MARKER_SHA=None
    if account is not None:
        if Path(account).is_symlink():raise ValueError('Gameplay account directory alias refused')
        account=Path(account).resolve();validate(account)
        ACCOUNT=account;MARKER_SHA=sha(account/MARKER)

def selected(account):
    if ACCOUNT is None or Path(account).resolve()!=ACCOUNT:return False
    if sha(ACCOUNT/MARKER)!=MARKER_SHA:raise ValueError('Gameplay selector changed during runtime')
    return True

def validate_selectors(paths):
    names=('profile.json','football.json','content.json','packs.json','seasons.json','definition.json','control.json')
    if len(paths)!=len(names) or any(p is None for p in paths):raise ValueError('Explicit gameplay selectors required')
    paths=[Path(p) for p in paths];account=paths[0].resolve().parent
    if not selected(account) or any(p.name!=name or p.is_symlink() or p.resolve().parent!=account for p,name in zip(paths,names)):raise ValueError('Gameplay selectors differ')
    validate(account);return account
