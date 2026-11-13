"""Certificate-backed normal admission for the existing season reset journal."""
import json
from pathlib import Path
from .season_choice_release import ROOT, REAL, ordinary, sha

MARKER='season-forfeit-release.json'
VERSION='local_season_forfeit_release_v1'
STATUS='STOCK_VERIFIED_SEASON_FORFEIT'
POLICIES=(ROOT/'server/policy/season-forfeit-v1.json',ROOT/'server/policy/offline-seasons-revival.json')
FEATURES=('current_points_stay_or_relegate','division10_floor','no_new_rewards',
          'earned_history_preserved','original_next_selection','cached_legacy_rules_preserved',
          'phase_scoped_empty_reset_retries')


def marker(account,archive,certificate):
    account=Path(account).resolve();archive=Path(archive).resolve();certificate=Path(certificate).resolve()
    return dict(version=VERSION,account=str(account),origin_archive=str(archive),
        origin_manifest_sha256=sha(archive/'.lab-snapshot.json'),certificate=str(certificate),
        certificate_sha256=sha(certificate),policies={str(p):sha(p) for p in POLICIES},features=list(FEATURES))


def validate(account):
    account=Path(account)
    if account.is_symlink():raise ValueError('Forfeit release account alias refused')
    account=account.resolve()
    if account!=REAL and (ROOT/'reports' not in account.parents or account.name!='isolated-account'):
        raise ValueError('Unknown forfeiture release account')
    value=json.loads(ordinary(account/MARKER).read_bytes())
    archive=Path(value['origin_archive']);certificate=Path(value['certificate'])
    if archive.is_symlink() or ROOT/'reports' not in archive.resolve().parents or archive.resolve()==account:
        raise ValueError('Separate forfeiture release backup required')
    manifest=json.loads(ordinary(archive/'.lab-snapshot.json').read_bytes())
    if not {'profile.json','native-seasons.json','seasons.json','definition.json','season-choice-release.json'}<=manifest['sha256'].keys():
        raise ValueError('Incomplete forfeiture release backup')
    for name,digest in manifest['sha256'].items():
        if Path(name).name!=name or sha(ordinary(archive/name))!=digest:
            raise ValueError('Forfeiture release backup changed')
    if certificate.is_symlink() or ROOT/'reports' not in certificate.resolve().parents:
        raise ValueError('Local frozen forfeiture certificate required')
    if value!=marker(account,archive,certificate):raise ValueError('Forfeiture release configuration changed')
    proof=json.loads(ordinary(certificate).read_bytes())
    required=('native_reset_verified','relegation_verified','no_reward_delta_verified','history_preserved',
              'original_selection_verified','legacy_rules_verified','restart_verified','retry_verified',
              'repeated_empty_forfeits_verified')
    if proof.get('status')!=STATUS or not all(proof.get(k) is True for k in required) or not proof.get('proof_files'):
        raise ValueError('Incomplete native forfeiture certificate')
    for name,digest in proof['proof_files'].items():
        file=ROOT/name
        if not any(p in file.resolve().parents for p in (ROOT/'reports',ROOT/'captures')) or sha(ordinary(file))!=digest:
            raise ValueError('Frozen forfeiture proof changed')
    before=json.loads((archive/'profile.json').read_bytes());current=json.loads(ordinary(account/'profile.json').read_bytes())
    if any(before[k]!=current[k] for k in ('persona_id','identity_pid','user_id')):
        raise ValueError('Forfeiture release identity changed')
    return value
