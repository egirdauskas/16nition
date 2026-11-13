"""Certificate-backed admission of the original single-player tournaments (GAME-012).

Mirrors player_exchange_release: the normal account is admitted only through a
hash-pinned marker naming a separate archived backup, the certified catalog and
temporary reward policy, and a certificate whose archived evidence is unchanged.
"""
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REAL=ROOT/'server/data/development/fm16in2026'
MARKER='tournament-release.json'
VERSION='tournament_release_v1'
CERT_ROOT=ROOT/'reports/single-player-tournaments'
CERT_ROOTS=(CERT_ROOT,ROOT/'reports/tournament-rewards')
CHECKS=('original_ui','entry_and_cold_resume','round_progression','championship_no_client_save',
        'elimination_no_client_save','forfeit_delete','re_entry_after_terminal','played_match',
        'interrupted_match_supersede','concurrent_cups','eligibility_at_create','championship_reward_once',
        'restart_verified','exact_retry_verified','unrelated_preserved')


def sha(path):
    path=Path(path)
    if path.is_symlink() or path.stat().st_nlink!=1:raise ValueError('Tournament evidence alias refused')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def certificate(path,catalog_policy,reward_policy):
    path=Path(path).resolve()
    if not any(root in path.parents for root in CERT_ROOTS):raise ValueError('Tournament certificate location differs')
    proof=json.loads(path.read_bytes())
    _,_,checks,status=edition(reward_policy)
    if (proof.get('status')!=status or
            proof.get('catalog_policy_sha256')!=sha(catalog_policy) or
            proof.get('reward_policy_sha256')!=sha(reward_policy) or
            any(proof.get(k) is not True for k in checks) or
            type(proof.get('evidence')) is not dict or not proof['evidence']):
        raise ValueError('Incomplete tournament certificate')
    for name,digest in proof['evidence'].items():
        item=Path(name)
        if item.is_absolute() or '..' in item.parts:raise ValueError('Invalid tournament evidence path')
        item=ROOT/item
        if ROOT/'reports' not in item.parents and ROOT/'captures' not in item.parents:
            raise ValueError('Tournament evidence must be archived')
        if sha(item)!=digest:raise ValueError('Tournament evidence changed')
    return proof


# GAME-013 extension: same admission machinery, separate marker/certificate,
# selected by the reward policy version actually being enabled.
MARKER_V2='tournament-release-v2.json'
VERSION_V2='tournament_release_v2'
CHECKS_V2=('original_ui','bonus_panel_first_and_repeat','brazil_entry_and_requirement',
           'match_rewards_report_bound','awards_completion_split','first_win_championship_packs',
           'repeat_championship_coins_only','draw_report_staged_end_held','cold_restart_ownership',
           'exact_retry_verified','unrelated_preserved')


def edition(reward_policy):
    """(marker, version, checks, status) for the reward policy being admitted."""
    version=json.loads(Path(reward_policy).read_bytes()).get('version')
    if version=='tournament_rewards_v2':
        return MARKER_V2,VERSION_V2,CHECKS_V2,'STOCK_VERIFIED_TOURNAMENT_REWARDS_V2'
    return MARKER,VERSION,CHECKS,'STOCK_VERIFIED_SINGLE_PLAYER_TOURNAMENTS'


def admitted(account):
    return Path(account).resolve()==REAL and (REAL/MARKER).is_file()


def admit(account,catalog_policy,reward_policy):
    marker,version,_,_=edition(reward_policy)
    account=Path(account).resolve();path=account/marker
    if account!=REAL or not path.is_file():raise ValueError('Uncertified tournaments require archived isolation')
    value=json.loads(path.read_bytes())
    if (set(value)!={'version','account','archive','manifest_sha256','catalog_policy_sha256','reward_policy_sha256',
                     'certificate','certificate_sha256'} or
            value['version']!=version or value['account']!=str(account) or
            value['catalog_policy_sha256']!=sha(catalog_policy) or value['reward_policy_sha256']!=sha(reward_policy)):
        raise ValueError('Invalid tournament release marker')
    sha(path)
    archive=Path(value['archive']).resolve()
    if (not any(root in archive.parents for root in CERT_ROOTS) or archive==account or
            sha(archive/'.lab-snapshot.json')!=value['manifest_sha256']):raise ValueError('Separate tournament backup required')
    files=json.loads((archive/'.lab-snapshot.json').read_bytes())['sha256']
    if not {'profile.json','football.json','control.json'}<=files.keys():raise ValueError('Incomplete tournament backup')
    for name,digest in files.items():
        if Path(name).name!=name or sha(archive/name)!=digest:raise ValueError('Tournament backup changed')
    before,current=[json.loads((p/'profile.json').read_bytes()) for p in (archive,account)]
    if any(before.get(k)!=current.get(k) for k in ('persona_id','identity_pid','user_id')):raise ValueError('Tournament owner changed')
    if sha(value['certificate'])!=value['certificate_sha256']:raise ValueError('Tournament certificate changed')
    certificate(value['certificate'],catalog_policy,reward_policy)
    return value
