"""Only the proven startup settings dependency; no other FUT services.

02303458 accepts {} without any required-field rejection; run31 proves its
failure blocks login. Optional numeric settings keep constructor defaults.
"""
from .identity import json_response

def response_for(method, target, headers, body, native_simulation_discovery=False):
    if (method == 'GET' and target == '/ut/game/fifaworldmobile/settings'
        and headers.get(b'host') == b'10.0.2.2:18081'
        and headers.get(b'x-ut-sid') == b'fifa16-local-sid' and body == b''):
        # Original settings parser02303458 -> setter021728f4: nonzero numeric
        # enableSimMatch clears settings+80. Discovery only; no Sim success DTO.
        return json_response({'configs':[{'type':'enableSimMatch','value':1}]} if native_simulation_discovery is True else {})
    return None

def validate_simulation_discovery(account_paths):
    """Require one fresh hash-verified disposable copy before a lab listener.

    This grants no progression/rewards and does not relax simulator exclusivity.
    The regular mobile backend and every server/data account are refused.
    """
    import hashlib,json
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    if not account_paths or any(path is None for path in account_paths):
        raise ValueError('Simulation discovery needs explicit isolated account selectors')
    paths=[Path(path) for path in account_paths]
    account=paths[0].resolve().parent
    if root/'reports' not in account.parents or any(path.is_symlink() for path in paths):
        raise ValueError('Simulation discovery requires a disposable reports account')
    if any(path.resolve().parent!=account for path in paths):
        raise ValueError('Simulation discovery selectors must share one isolated account')
    manifest=json.loads((account/'.lab-snapshot.json').read_text())
    expected=manifest['sha256']
    if not {'profile.json','football.json','seasons.json','control.json','packs.json','content.json','definition.json'}<=expected.keys():
        raise ValueError('Incomplete simulation discovery snapshot')
    real=root/'server/data/development/fm16in2026'
    for name,sha in expected.items():
        if Path(name).name!=name:raise ValueError('Invalid snapshot filename')
        file=account/name
        if file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest()!=sha:
            raise ValueError('Simulation discovery snapshot differs')
        original=real/name
        if original.exists() and file.samefile(original):raise ValueError('Real account alias refused')
    return account
