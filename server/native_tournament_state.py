"""1354 initial native tournament checkpoint, isolated and reward-free.

The original client owns bracket generation. Preserve its encoded checkpoint;
do not interpret scores or turn opaque data into match/reward authority.
"""
import base64
import hashlib
import json
import struct
import zlib
from pathlib import Path
from .account_transaction import account_locked, atomic

NAME = 'native-tournaments.json'
VERSION = 'native_tournament_initial_v1'
CUPS = (201, 202, 203, 204, 205)


def path_for(account, tournament_id=201):
    #1372 concurrent cups: Starter Cup keeps the original file name unchanged.
    if tournament_id not in CUPS: raise ValueError('Unknown tournament')
    return Path(account)/(NAME if tournament_id == 201 else f'native-tournaments-{tournament_id}.json')


def load_all(account):
    return {t: v for t in CUPS if (v := load(account, t)) is not None}


def initial(body, tournament_id):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Duplicate tournament field')
            result[key] = value
        return result
    value = json.loads(body, object_pairs_hook=unique)
    if (type(value) is not dict or set(value) != {'round', 'tournamentData'} or
            type(value['round']) is not int or value['round'] != 1 or
            type(value['tournamentData']) is not str or tournament_id not in CUPS):
        raise ValueError('Only captured initial tournament checkpoint admitted')
    wire = base64.b64decode(value['tournamentData'], validate=True)
    #1354 first native checkpoint: explicit length, gzip, cup ID and format tag.
    #Keep admission bounded to this recovered initial format, not later results.
    if len(wire) < 8 or struct.unpack('<I', wire[:4])[0] != 2797:
        raise ValueError('Unmapped tournament checkpoint size')
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try: raw = decoder.decompress(wire[4:], 2798)
    except zlib.error as exc: raise ValueError('Invalid tournament compression') from exc
    if (len(raw) != 2797 or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or
            struct.unpack_from('<3I', raw) != (tournament_id, 0, 20110813)):
        raise ValueError('Unmapped tournament checkpoint envelope/header')
    return {'version': VERSION, 'tournament_id': tournament_id,
            'round': 1, 'tournamentData': value['tournamentData'],
            'request_sha256': hashlib.sha256(body).hexdigest()}


def load(account, tournament_id=201):
    from .native_tournament_match import recover
    if (Path(account)/'native-tournament-sim.json').exists():recover(account)
    path = path_for(account, tournament_id)
    if not path.exists(): return None
    value = json.loads(path.read_bytes())
    if type(value) is not dict:raise ValueError("Invalid tournament state object")
    if value.get('tournament_id') != tournament_id:raise ValueError('Tournament file/cup mismatch')
    if value.get('version')=='native_tournament_initial_v2':
        if type(value.get('run_id')) is not str or len(value['run_id'])!=32:raise ValueError('Invalid tournament run identity')
        old={k:v for k,v in value.items() if k!='run_id'};old['version']=VERSION
        parsed=initial(json.dumps({k:old[k] for k in ('round','tournamentData')},separators=(',',':')).encode(),old['tournament_id'])
        if set(old)!=set(parsed) or any(old[k]!=parsed[k] for k in old if k!='request_sha256'):raise ValueError('Invalid initial tournament run')
        return value
    if value.get('version')=='native_tournament_progress_v1':
        if set(value)!={'version','tournament_id','round','tournamentData','request_sha256','source_id','prior_checkpoint_sha256'} and set(value)!={'version','tournament_id','round','tournamentData','request_sha256','source_id','prior_checkpoint_sha256','run_id'}:raise ValueError('Invalid tournament progress fields')
        parsed,raw=checkpoint(json.dumps({k:value[k] for k in ('round','tournamentData')}).encode(),value['tournament_id'])
        if int.from_bytes(raw[4:8],'little')!=value['round']-1 or any(type(value[k]) is not str or len(value[k])!=64 for k in ('request_sha256','source_id','prior_checkpoint_sha256')):raise ValueError('Invalid tournament progress identity')
        return value
    if (type(value) is not dict or set(value) != {'version', 'tournament_id', 'round',
            'tournamentData', 'request_sha256'} or value['version'] != VERSION or
            type(value['request_sha256']) is not str or len(value['request_sha256']) != 64):
        raise ValueError('Unknown preserved tournament state')
    body = json.dumps({k: value[k] for k in ('round', 'tournamentData')}).encode()
    parsed = initial(body, value['tournament_id'])
    if any(parsed[k] != value[k] for k in parsed if k != 'request_sha256'):
        raise ValueError('Invalid preserved tournament state')
    return value


@account_locked
def preview(account, body, tournament_id):
    candidate = initial(body, tournament_id)
    existing = load(account, tournament_id)
    from .native_tournament_match import closed
    if existing is not None and closed(account,existing) is None:
        normalized={k:v for k,v in existing.items() if k!='run_id'}
        if normalized.get('version')=='native_tournament_initial_v2':normalized['version']=VERSION
        if normalized!=candidate:raise ValueError('Conflicting tournament checkpoint')
        return existing
    #No financial/inventory projection, and no outstanding native match allowed.
    seasons = json.loads((Path(account)/'native-seasons.json').read_bytes())
    if seasons.get('active_match') or seasons.get('prepared'):
        raise ValueError('Pending native match')
    #1373: the stock client enters without checking requirements (teams GET +
    #initial save) and enforces them at squad CONTINUE (INVALID SQUAD popup).
    #Entry is free and reward-free; backend eligibility is enforced at match
    #Create (native_tournament_match.inspect_create), where it matters.
    return candidate


@account_locked
def commit(account, body, tournament_id):
    value = preview(account, body, tournament_id)
    path = path_for(account, tournament_id)
    old=load(account, tournament_id)
    from .native_tournament_match import closed,settle
    if not path.exists() or closed(account,old) is not None:
        if old is not None:settle(account,old)
        import uuid
        value={**value,'version':'native_tournament_initial_v2','run_id':uuid.uuid4().hex}
        atomic(path, (json.dumps(value, sort_keys=True, indent=2)+'\n').encode())
    return value


def checkpoint(body,tournament_id):
    """Decode original bounded checkpoint bytes only; never generate a vector.

    0101d53c/0101d5e4 transfer the explicit ID/round pair before opaque data.
    Semantic admission belongs to the source-bound result/save coordinator.
    """
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('Duplicate checkpoint field')
            value[key]=item
        return value
    value=json.loads(body,object_pairs_hook=unique)
    if (type(value) is not dict or set(value)!={'round','tournamentData'} or
            type(value['round']) is not int or not 1<=value['round']<=5 or
            type(value['tournamentData']) is not str or type(tournament_id) is not int or
            tournament_id not in CUPS):raise ValueError('Invalid tournament checkpoint')
    wire=base64.b64decode(value['tournamentData'],validate=True)
    if len(wire)<8:raise ValueError('Truncated checkpoint')
    size=struct.unpack_from('<I',wire)[0]
    if not 12<=size<=65536:raise ValueError('Unbounded checkpoint')
    d=zlib.decompressobj(16+zlib.MAX_WBITS)
    try:raw=d.decompress(wire[4:],size+1)
    except zlib.error as exc:raise ValueError('Invalid checkpoint compression') from exc
    if len(raw)!=size or not d.eof or d.unused_data or d.unconsumed_tail:raise ValueError('Checkpoint length/CRC mismatch')
    identity,round_index=struct.unpack_from('<2I',raw)
    if identity!=tournament_id or round_index>4:raise ValueError('Checkpoint identity/round mismatch')
    return value,raw
