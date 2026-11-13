"""Explicit normal-account admission of stock-tested played/Sim forfeiture."""
import json
from pathlib import Path
from .season_choice_release import ROOT,REAL,ordinary,sha

MARKER='match-forfeit-release.json'
VERSION='local_match_forfeit_release_v1'
STATUS='STOCK_VERIFIED_MATCH_FORFEIT'
REQUIRED=('played_verified','sim_verified','cancel_unchanged_verified','no_match_rewards_verified',
          'terminal_season_verified','normal_routing_verified','restart_verified','retry_verified')


def marker(account,archive,certificate):
    return dict(version=VERSION,account=str(Path(account).resolve()),origin_archive=str(Path(archive).resolve()),
        origin_manifest_sha256=sha(Path(archive)/'.lab-snapshot.json'),certificate=str(Path(certificate).resolve()),
        certificate_sha256=sha(Path(certificate)))


def validate(account):
    account=Path(account)
    if account.is_symlink():raise ValueError('Match forfeiture account alias refused')
    account=account.resolve()
    if account!=REAL and (ROOT/'reports' not in account.parents or account.name!='isolated-account'):
        raise ValueError('Unknown match forfeiture account')
    value=json.loads(ordinary(account/MARKER).read_bytes())
    archive=Path(value['origin_archive']);certificate=Path(value['certificate'])
    if (archive.is_symlink() or ROOT/'reports' not in archive.resolve().parents or archive.resolve()==account
            or certificate.is_symlink() or ROOT/'reports' not in certificate.resolve().parents):
        raise ValueError('Separate preserved match forfeiture proof required')
    manifest=json.loads(ordinary(archive/'.lab-snapshot.json').read_bytes())
    if not {'profile.json','native-seasons.json','seasons.json','definition.json','season-choice-release.json'}<=manifest['sha256'].keys():
        raise ValueError('Incomplete match forfeiture backup')
    for name,digest in manifest['sha256'].items():
        if Path(name).name!=name or sha(ordinary(archive/name))!=digest:raise ValueError('Match forfeiture archive changed')
    if value!=marker(account,archive,certificate):raise ValueError('Match forfeiture admission changed')
    proof=json.loads(ordinary(certificate).read_bytes())
    if proof.get('status')!=STATUS or not all(proof.get(k) is True for k in REQUIRED) or not proof.get('proof_files'):
        raise ValueError('Incomplete stock match forfeiture certificate')
    for name,digest in proof['proof_files'].items():
        file=ROOT/name
        if not any(p in file.resolve().parents for p in (ROOT/'reports',ROOT/'captures')) or sha(ordinary(file))!=digest:
            raise ValueError('Frozen match forfeiture evidence changed')
    before=json.loads((archive/'profile.json').read_bytes());current=json.loads(ordinary(account/'profile.json').read_bytes())
    if any(before[k]!=current[k] for k in ('persona_id','identity_pid','user_id')):
        raise ValueError('Match forfeiture account owner changed')
    return value
