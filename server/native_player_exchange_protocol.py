"""Original1337 range read and1338 source-bound Start, isolated opt-ins only.

01036d0c reads a root JSON array, fields10e/22b/22c, and sorts on upperLimit.
00b63f6c chooses the first upperLimit >= the summed owned discard values.
"""
from pathlib import Path
import json
from .game_auth import SID
from .identity import json_response
from .player_exchange_policy import load,native_ranges

ACCOUNT = POLICY = COORDINATOR = POLICY_PATH = None
START_ENABLED = False
RANGE_PATH = '/ut/game/fifaworldmobile/item/exchange/range'
START_PATH = '/ut/game/fifaworldmobile/item/exchange/start'
RETRY_PATH = '/ut/game/fifaworldmobile/item/exchange/retry'
END_PATH = '/ut/game/fifaworldmobile/item/exchange/end'


def configure(account=None, policy_path=None, *, start=False):
    global ACCOUNT,POLICY,COORDINATOR,POLICY_PATH,START_ENABLED
    ACCOUNT = POLICY = COORDINATOR = POLICY_PATH = None
    START_ENABLED = False
    if account is None:
        if policy_path is not None or start:raise ValueError('Exchange policy/Start requires explicit account')
        return
    root = Path(__file__).resolve().parents[1]
    account = Path(account).resolve()
    from .fresh_account_runtime import selected as fresh_selected
    if not fresh_selected(account) and (root/'reports' not in account.parents or account.name != 'isolated-account' or
            not (account/'.lab-snapshot.json').is_file()):
        from .player_exchange_release import admit
        admit(account,policy_path)
    POLICY,_ = load(policy_path)
    ACCOUNT = account
    POLICY_PATH = Path(policy_path).resolve()
    if type(start) is not bool:raise ValueError('Explicit exchange Start selector required')
    START_ENABLED = start


def coordinator(account):
    global COORDINATOR
    if not START_ENABLED or ACCOUNT is None or account is None or Path(account).resolve()!=ACCOUNT:
        return None
    if COORDINATOR is None:
        from .player_exchange import PlayerExchangeCoordinator
        COORDINATOR = PlayerExchangeCoordinator(ACCOUNT,policy_path=POLICY_PATH,enabled=True)
    return COORDINATOR


def recover(account):
    c=coordinator(account)
    if c:c.recover()


def decode_start(method,target,headers,body,c):
    if (method!='POST' or target!=START_PATH or headers.get(b'host')!=b'10.0.2.2:18081' or
            headers.get(b'x-ut-sid')!=SID.encode() or headers.get(b'content-type')!=b'application/json' or
            headers.get(b'content-length')!=str(len(body)).encode()):
        raise ValueError('Not the captured authenticated exchange Start')
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('Duplicate exchange field')
            value[key]=item
        return value
    value=json.loads(body,object_pairs_hook=unique)
    if type(value) is not dict or set(value)!={'itemIds'}:
        raise ValueError('Unmapped exchange Start body')
    session=headers.get(b'x-fifa-local-original-sid',headers[b'x-ut-sid']).decode('ascii')
    return c.request('start',session,ids=value['itemIds'])


def decode_result(method,target,headers,body,c):
    # Shared Start/Retry request class01037840; Confirm01038024 formats /end.
    # Result requests carry no IDs/body; manager0218396c/021839a4 owns context.
    if (method!='POST' or target not in (RETRY_PATH,END_PATH) or body or
            headers.get(b'host')!=b'10.0.2.2:18081' or headers.get(b'x-ut-sid')!=SID.encode() or
            headers.get(b'content-length',b'0')!=b'0'):
        raise ValueError('Not an authenticated empty exchange result request')
    session=headers.get(b'x-fifa-local-original-sid',headers[b'x-ut-sid']).decode('ascii')
    return c.session_request('retry' if target==RETRY_PATH else 'confirm',session)


def decode(method,target,headers,body,c):
    if target==START_PATH:return decode_start(method,target,headers,body,c)
    return decode_result(method,target,headers,body,c)


def response_for(method,target,headers,body,account):
    if ACCOUNT is None or account is None or Path(account).resolve()!=ACCOUNT:
        return None
    if (method=='GET' and target==RANGE_PATH and not body and
            headers.get(b'host')==b'10.0.2.2:18081' and headers.get(b'x-ut-sid')==SID.encode()):
        return json_response(native_ranges(POLICY))
    c=coordinator(account)
    if c is not None and target in (START_PATH,RETRY_PATH,END_PATH):
        try:return json_response(c.preview(decode(method,target,headers,body,c)))
        except (ValueError,TypeError,KeyError,UnicodeError):return None
    return None


def commit_request(method,target,headers,body,account):
    c=coordinator(account)
    if c is None or target not in (START_PATH,RETRY_PATH,END_PATH):return None
    try:request=decode(method,target,headers,body,c)
    except (ValueError,TypeError,KeyError,UnicodeError):return None
    return json_response(c.execute(request))
