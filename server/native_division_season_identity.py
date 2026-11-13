"""Prospective local service identities for native division-definition changes.

SeasonListCallback0100cdc8 keeps an existing SeasonInfo when an ID is reused.
These are local service IDs, not historical EA content/resource IDs. The match
source pins the choice; the existing atomic completion journal commits it.
"""
import json
from pathlib import Path

VERSION='local_division_season_identity_v1'
KEY='division_season_identity'
ROOT=Path(__file__).resolve().parents[1]
REAL=ROOT/'server/data/development/fm16in2026'
MARKER='division-season-identity-release.json'
RELEASE_VERSION='local_division_season_identity_release_v1'
CONTRACT=ROOT/'reports/gameplay-sampling/2026-10-25-remaining-outcomes/promotion/identity-certificate.json'
EVIDENCE=CONTRACT.parent/'identity-evidence-hashes.json'


def snapshot(current, state):
    value={'version':VERSION,'season_id':current.season_id,'changed_division_season_id':current.season_id+1}
    validate(value,current.season_id)
    used={json.loads(bytes.fromhex(s['create_body_hex']))['seasonId'] for s in state['matches']+state.get('aborted_matches',[])}
    if value['changed_division_season_id'] in used:
        raise ValueError('Prospective native season ID already used; no source accepted')
    return value


def validate(value, season_id):
    if (type(value) is not dict or set(value)!={'version','season_id','changed_division_season_id'} or
        value['version']!=VERSION or type(value['season_id']) is not int or
        type(value['changed_division_season_id']) is not int or
        not 0<value['season_id']<0x7fffffff or value['season_id']!=season_id or
        value['changed_division_season_id']!=season_id+1):
        raise ValueError('Invalid pinned native division season identity')
    return value


def next_id(source, outcome):
    current=json.loads(bytes.fromhex(source['atomic_match']['season_before_hex']))['current']
    season_id=current['season_id']
    value=source.get(KEY)
    if value is None:return season_id
    validate(value,season_id)
    if json.loads(bytes.fromhex(source['create_body_hex']))['seasonId']!=season_id:
        raise ValueError('Native season identity differs from accepted Create')
    return value['changed_division_season_id'] if outcome['proposed_next_division']!=current['division_index'] else season_id


def marker(account,archive):
    from .sim_completion_release import sha
    return {'version':RELEASE_VERSION,'account':str(Path(account).resolve()),
        'origin_archive':str(Path(archive).resolve()),
        'origin_manifest_sha256':sha(Path(archive)/'.lab-snapshot.json'),
        'certificate':str(CONTRACT),'certificate_sha256':sha(CONTRACT),
        'evidence_sha256':sha(EVIDENCE)}


def validate_deployment(account):
    """Existing configuration-only release pattern; no domain projections."""
    from .sim_completion_release import sha,ordinary_file,CONFIG
    account=Path(account)
    if account.is_symlink():raise ValueError('Division identity account alias refused')
    account=account.resolve()
    if account!=REAL and (ROOT/'reports' not in account.parents or account.name!='isolated-account'):
        raise ValueError('Division identity account differs')
    for path in account.glob('*.json'):ordinary_file(path)
    value=json.loads(ordinary_file(account/MARKER).read_bytes())
    if (set(value)!={'version','account','origin_archive','origin_manifest_sha256','certificate','certificate_sha256','evidence_sha256'} or
        value['version']!=RELEASE_VERSION or value['account']!=str(account)):
        raise ValueError('Invalid division identity admission')
    archive=Path(value['origin_archive'])
    if archive.is_symlink():raise ValueError('Division identity archive alias refused')
    archive=archive.resolve()
    if ROOT/'reports' not in archive.parents or archive==account or account in archive.parents:
        raise ValueError('Separate division identity archive required')
    manifest=ordinary_file(archive/'.lab-snapshot.json')
    if sha(manifest)!=value['origin_manifest_sha256']:raise ValueError('Division identity archive manifest changed')
    files=json.loads(manifest.read_bytes())['sha256']
    if not {'profile.json','football.json','packs.json','purchases.json','native-seasons.json','definition.json','seasons.json',
            'control.json','gameplay-release.json','atomic-match-release.json','sim-completion-release.json'}<=files.keys():
        raise ValueError('Incomplete division identity archive')
    for name,digest in files.items():
        if Path(name).name!=name or sha(ordinary_file(archive/name))!=digest:raise ValueError('Division identity archive changed')
    old=json.loads((archive/'profile.json').read_bytes());current=json.loads((account/'profile.json').read_bytes())
    if any(old[k]!=current[k] for k in ('persona_id','identity_pid','user_id')):raise ValueError('Division identity owner changed')
    from .store_release import configuration_preserved
    if not configuration_preserved(account,archive):raise ValueError('Division identity supported configuration changed')
    for name in ('gameplay-release.json','atomic-match-release.json','sim-completion-release.json'):
        if sha(account/name)!=sha(archive/name):raise ValueError('Division identity supported configuration changed')
    if (Path(value['certificate'])!=CONTRACT or sha(ordinary_file(CONTRACT))!=value['certificate_sha256'] or
        sha(ordinary_file(EVIDENCE))!=value['evidence_sha256']):raise ValueError('Division identity certificate/evidence changed')
    proof=json.loads(CONTRACT.read_bytes())
    if (proof.get('status')!='STOCK_VERIFIED_DISTINCT_DIVISION_SEASON_IDENTITIES' or
        proof.get('policy_version')!=VERSION or
        not all(proof.get(k) is True for k in ('same_session_selector_verified','original_next_zero_anchor_verified',
            'first_next_fixture_without_client_restart','backend_restart_verified','client_restart_verified','no_duplicate_rewards_or_ownership')) or
        proof.get('new_season_bonus_or_pack_enabled') is not False or
        (proof.get('old_season_id'),proof.get('next_season_id'))!=(1,2) or
        (proof.get('exact_final_and_anchor_retries'),proof.get('exact_first_next_retries'))!=(18,18) or
        not all(type(proof.get(k)) is int and proof[k]>0 for k in ('final_capture','first_next_fixture_capture','full_restart_capture')) or
        len({proof['final_capture'],proof['first_next_fixture_capture'],proof['full_restart_capture']})!=3):
        raise ValueError('Division identity certificate incomplete')
    return value
