"""Captured single DiscardCard and731 bulk query, explicit account opt-in."""
import re
from pathlib import Path
from .game_auth import SID
from .identity import json_response
from .native_quick_sell import selection
from .account_transaction import account_locked
COORDINATOR=None
PREFIX='/ut/delete/game/fifaworldmobile/item'

def configure(coordinator=None):
    global COORDINATOR
    COORDINATOR=coordinator

def selected(account):
    return COORDINATOR if COORDINATOR is not None and account is not None and Path(account).resolve()==COORDINATOR.account else None

def recover(football_state):
    c=selected(Path(football_state).parent if football_state else None)
    if c:c.recover()

def decode(method,target,headers,body):
    if (method!='GET' or body or headers.get(b'host')!=b'10.0.2.2:18081' or
        headers.get(b'x-ut-sid')!=SID.encode() or headers.get(b'content-length',b'0')!=b'0'):
        raise ValueError('Not authenticated captured quick-sell request')
    if re.fullmatch(re.escape(PREFIX)+r'/[1-9][0-9]*',target):ids=[int(target[len(PREFIX)+1:])]
    elif re.fullmatch(re.escape(PREFIX)+r'\?itemIds=[1-9][0-9]*(,[1-9][0-9]*)*',target):
        ids=[int(v) for v in target.split('=',1)[1].split(',')]
    else:raise ValueError('Unmapped quick-sell URI')
    selection(ids)
    return ids

@account_locked
def response_for(method,target,headers,body,store):
    c=selected(store.path.parent)
    if c is None:return None
    try:ids=decode(method,target,headers,body);r=c.preview(ids)
    except (ValueError,KeyError,TypeError,UnicodeError):return None
    # Retries following a legitimate later spend must not reinstall an old balance.
    prior=any(v['source_ids']==sorted(ids) for v in c.inspect()['receipts'])
    credits=c.profile.load().credits if prior else r['credits_after']
    return json_response({'totalCredits':credits,'items':[{'id':i} for i in ids]})

@account_locked
def commit_request(method,target,headers,body,store):
    c=selected(store.path.parent)
    if c is None:return None
    try:ids=decode(method,target,headers,body);c.preview(ids)
    except (ValueError,KeyError,TypeError,UnicodeError):return None
    c.redeem(ids)
    return json_response({'totalCredits':c.profile.load().credits,'items':[{'id':i} for i in ids]})

def project_item(value,item,account):
    from .reward_ownership import untradeable
    restricted=untradeable(account,item.instance_id)
    # Original01028fc0 boolean key0x229 inverts to item+0x50. Static
    # contract mapped; positive reward ownership still requires native proof.
    if restricted:value={**value,'untradeable':True,'discardValue':0}
    if selected(account) is None:return value
    from .quick_sell_policy import quote
    try:coins=quote(item,untradeable=restricted)['coins']
    except ValueError:return value
    return {**value,'discardValue':coins}
