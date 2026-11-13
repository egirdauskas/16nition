"""Source-bound Player Exchanges using the existing account lock/CAS journal.

Only transient prepared intents retain complete football images. Permanent
receipts retain source IDs, output references and one shared policy snapshot.
Wallet, XP, squads, packs and supplied card metadata are never rewritten.
"""
import copy
from dataclasses import asdict
from functools import lru_cache
import hashlib
import json
import uuid

from .account_transaction import account_locked,atomic,recover_images
from .native_free_coins import FreeCoinsCoordinator,encode,digest
from .local_football import OwnedPlayerItem,owned_instance_ids,item_pile
from .local_packs import reviewed_player_pool,player_formation
from .player_exchange_policy import load,validate,range_for
from .quick_sell_policy import quote


def sources(ids):
    if (type(ids) not in (list,tuple) or not 2 <= len(ids) <= 10 or
            any(type(i) is not int or not 0 < i < 0x8000000000000000 for i in ids) or
            len(set(ids)) != len(ids)):
        raise ValueError('Exchange requires two to ten distinct owned player IDs')
    return sorted(ids)


@lru_cache(maxsize=1)
def pools():
    result=[]
    for quality in ('bronze','silver','gold'):
        values=reviewed_player_pool(quality,None)
        for rare in (False,True):
            pool=tuple(sorted((v for v in values if bool(v.special_version_id or v.base_rare)==rare),
                key=lambda v:(v.resource_id,v.special_version_id or '')))
            if not pool:raise ValueError('Missing admitted exchange player tier')
            result.append(pool)
    return tuple(result)


def pick(seed,label,size):
    """Reproducible SHA256 draw with rejection instead of modulo bias."""
    limit=(1 << 256)//size*size
    for attempt in range(100):
        value=int.from_bytes(hashlib.sha256(f'{seed}:{label}:{attempt}'.encode()).digest(),'big')
        if value < limit:return value % size
    raise ValueError('Exchange draw rejection limit')


def weighted(seed,label,weights):
    value=pick(seed,label,sum(weights))
    for index,weight in enumerate(weights):
        if value < weight:return index
        value-=weight
    raise ValueError('Invalid exchange weights')


class PlayerExchangeCoordinator(FreeCoinsCoordinator):
    def __init__(self,account,*,policy_path,enabled=False,fault=None):
        super().__init__(account,enabled=enabled,fault=fault)
        self.path=self.account/'player-exchanges.json'
        if self.path.is_symlink() or (self.path.exists() and self.path.stat().st_nlink != 1):
            raise ValueError('Exchange journal alias refused')
        self.policy,self.policy_source_sha=load(policy_path)

    def _empty(self):
        return dict(schema=1,account_id=str(uuid.uuid5(uuid.NAMESPACE_URL,str(self.account))),
            account_identity=self.identity(),policies={},receipts=[],active=None,prepared=None)

    def _validate(self,value):
        if (type(value) is not dict or set(value) != {'schema','account_id','account_identity','policies','receipts','active','prepared'} or
                type(value['schema']) is not int or value['schema'] != 1 or value['account_identity'] != self.identity() or
                type(value['policies']) is not dict or type(value['receipts']) is not list):
            raise ValueError('Invalid exchange journal/owner')
        namespace=uuid.UUID(value['account_id']);seen=set();allocated=set()
        for key,policy in value['policies'].items():
            validate(policy)
            if digest(encode(policy)) != key:raise ValueError('Exchange policy snapshot changed')
        for r in value['receipts']:
            if type(r) is not dict or set(r) != {'exchange_id','source_ids','source_quotes','score','policy_hash','session_hash','attempts','confirmed'}:
                raise ValueError('Invalid exchange receipt fields')
            ids=sources(r['source_ids']);key=str(uuid.uuid5(namespace,'exchange:'+','.join(map(str,ids))))
            if (ids != r['source_ids'] or seen.intersection(ids) or r['exchange_id'] != key or
                    r['policy_hash'] not in value['policies'] or type(r['confirmed']) is not bool or
                    type(r['source_quotes']) is not list or len(r['source_quotes']) != len(ids) or
                    type(r['attempts']) is not list or not 1 <= len(r['attempts']) <= 2):
                raise ValueError('Conflicting exchange source/receipt')
            seen.update(ids)
            for field in ('session_hash','policy_hash'):
                if type(r[field]) is not str or len(r[field]) != 64 or any(c not in '0123456789abcdef' for c in r[field]):
                    raise ValueError('Invalid exchange digest')
            for iid,q in zip(ids,r['source_quotes']):
                if q.get('instance_id') != iid or q.get('kind') != 'player':raise ValueError('Invalid exchange source quote')
                source=OwnedPlayerItem(iid,q['resource_id'],special_version_id=q['special_version_id'])
                if quote(source) != q:raise ValueError('Exchange source valuation changed')
            if type(r['score']) is not int or r['score'] != sum(q['coins'] for q in r['source_quotes']):
                raise ValueError('Exchange score mismatch')
            range_for(value['policies'][r['policy_hash']],r['score'])
            prior_ids=set(ids)
            for number,attempt in enumerate(r['attempts']):
                if type(attempt) is not dict or set(attempt) != {'items','reply_sha256'} or not 1 <= len(attempt['items']) <= 3:
                    raise ValueError('Invalid exchange result')
                from .draw_seal import is_sealed,exchange_key
                # Sealed history (draw_seal): verified by exact digest, not re-drawn from today's pool.
                if is_sealed(self.account,'player_exchanges',exchange_key(r),r):
                    expected=attempt['items']
                else:
                    expected=self._draw(r,value['policies'][r['policy_hash']],number,attempt['items'][0]['instance_id'])
                if attempt['items'] != expected:raise ValueError('Exchange draw/reference changed')
                output_ids={i['instance_id'] for i in expected}
                if len(output_ids) != len(expected) or prior_ids.intersection(output_ids) or allocated.intersection(output_ids):
                    raise ValueError('Exchange ownership identity reused')
                prior_ids.update(output_ids)
                allocated.update(output_ids)
                self._result(r,number)
        if value['active'] is not None:
            active=next((r for r in value['receipts'] if r['exchange_id']==value['active']),None)
            if active is None or active['confirmed']:raise ValueError('Invalid active exchange')
        if value['prepared'] is not None:
            p=value['prepared']
            if type(p) is not dict or set(p) != {'transaction_id','request','images','state_after'}:
                raise ValueError('Invalid exchange intent')
            uuid.UUID(p['transaction_id']);final=p['state_after']
            if final.get('prepared') is not None:raise ValueError('Nested exchange intent')
            self._validate(final)
            images=p['images']
            if (type(images) is not list or len(images) != 1 or set(images[0]) != {'name','before','after'} or
                    images[0]['name'] != 'football.json'):
                raise ValueError('Exchange intent may target only ownership')
            base=copy.deepcopy(value);base['prepared']=None
            before=json.loads(bytes.fromhex(images[0]['before']))
            request=p['request']
            pinned=final['policies'][request['policy_hash']] if request['operation']=='start' else None
            _,expected_state,expected_football=self._plan(base,before,request,pinned)
            if expected_state != final or encode(expected_football).hex() != images[0]['after']:
                raise ValueError('Exchange intent changes unrelated state')
        return value

    def _draw(self,receipt,policy,attempt,first):
        if type(first) is not int or not 0 < first <= 0x7ffffffffffffffc:
            raise ValueError('Invalid bounded exchange output allocation')
        seed=f"{receipt['exchange_id']}:{receipt['policy_hash']}:{attempt}"
        count=weighted(seed,'count',policy['reward_count_weights'])+1
        weights=range_for(policy,receipt['score'])['tier_weights'];selected=set();result=[]
        for index in range(count):
            tier=weighted(seed,f'tier:{index}',weights)
            pool=[v for v in pools()[tier] if (v.resource_id,v.special_version_id) not in selected]
            card=pool[pick(seed,f'player:{index}',len(pool))]
            selected.add((card.resource_id,card.special_version_id))
            item=OwnedPlayerItem(first+index,card.resource_id,fitness=99,
                formation_id=player_formation(int(uuid.UUID(receipt['exchange_id'])),card.resource_id),
                special_version_id=card.special_version_id)
            result.append({k:v for k,v in asdict(item).items() if v is not None})
        return result

    def _result(self,receipt,attempt):
        from .football_protocol import encode_item
        items=[]
        for row in receipt['attempts'][attempt]['items']:
            item=OwnedPlayerItem(**row);encoded=encode_item(item,self.football.catalog,True)
            encoded.update(discardValue=quote(item)['coins'],untradeable=False)
            items.append(encoded)
        result={'retry':attempt==0,'itemList':items}
        expected=receipt['attempts'][attempt].get('reply_sha256')
        if expected is not None and expected != digest(json.dumps(result,separators=(',',':')).encode()):
            raise ValueError('Exchange response projection changed')
        return result

    def _delta(self,before,remove,items):
        state=self.football.decode(before,self.identity()['persona_id']);owned=owned_instance_ids(state)
        if any(i not in owned for i in remove):raise ValueError('Exchange source is not owned')
        first=state.next_instance_id or max(owned,default=0)+1
        if [i['instance_id'] for i in items] != list(range(first,first+len(items))):
            raise ValueError('Exchange must allocate fresh monotonic ownership')
        after=copy.deepcopy(before)
        after['owned_items']=sorted([r for r in before['owned_items'] if r['instance_id'] not in remove]+items,key=lambda i:i['instance_id'])
        after['inventory_locations']=[r for r in before.get('inventory_locations',[]) if r['instance_id'] not in remove]+[
            {'instance_id':r['instance_id'],'pile':'unassigned'} for r in items]
        after['next_instance_id']=first+len(items)
        after['retired_instance_ids']=sorted(set(before.get('retired_instance_ids',[]))|set(remove))
        self.football.decode(after,self.identity()['persona_id'])
        return after

    def _plan(self,value,football,request,pinned=None):
        if set(request) != {'operation','ids','exchange_id','session_hash','policy_hash'}:
            raise ValueError('Invalid exchange operation identity')
        state=self.football.decode(football,self.identity()['persona_id']);final=copy.deepcopy(value)
        operation=request['operation'];remove=[];items=[]
        if operation=='start':
            ids=sources(request['ids']);key=str(uuid.uuid5(uuid.UUID(value['account_id']),'exchange:'+','.join(map(str,ids))))
            prior=next((r for r in value['receipts'] if r['exchange_id']==key),None)
            if prior:return self._result(prior,0),None,None
            active=next((r for r in final['receipts'] if r['exchange_id']==final['active']),None)
            if active is not None:
                if active['session_hash']==request['session_hash']:raise ValueError('Confirm the current exchange before starting another')
                # A new login keeps the prior already-owned result after a lost
                # result screen; it never silently consumes it as a free retry.
                active['confirmed']=True;final['active']=None
            owned={i.instance_id:i for i in state.owned_items}
            protected={s.instance_id for s in state.active_lineup}
            for squad in state.other_squads:protected.update(s.instance_id for s in squad.lineup)
            if any(i not in owned or item_pile(state,i)!='club' or i in protected or i in state.untradeable_instance_ids for i in ids):
                raise ValueError('Exchange requires free tradable Club players outside all saved squads')
            policy=validate(pinned or self.policy);policy_hash=digest(encode(policy))
            if request['policy_hash'] != policy_hash:raise ValueError('Exchange policy changed before commit')
            quotes=[quote(owned[i]) for i in ids]
            receipt=dict(exchange_id=key,source_ids=ids,source_quotes=quotes,score=sum(q['coins'] for q in quotes),
                policy_hash=policy_hash,session_hash=request['session_hash'],attempts=[],confirmed=False)
            final['policies'][policy_hash]=policy;final['receipts'].append(receipt);final['active']=key
            remove=ids;number=0
        elif operation in ('retry','confirm'):
            receipt=next((r for r in final['receipts'] if r['exchange_id']==request['exchange_id']),None)
            if receipt is None or receipt['session_hash'] != request['session_hash']:
                raise ValueError('Foreign or stale exchange result session')
            if operation=='confirm':
                if receipt['confirmed']:return {},None,None
                if final['active'] != receipt['exchange_id']:raise ValueError('Inactive exchange confirmation')
                receipt['confirmed']=True;final['active']=None
                return {},final,football
            if len(receipt['attempts'])==2:return self._result(receipt,1),None,None
            if receipt['confirmed'] or final['active'] != receipt['exchange_id']:raise ValueError('Exchange result already accepted')
            remove=[i['instance_id'] for i in receipt['attempts'][0]['items']]
            owned={i.instance_id:i for i in state.owned_items}
            if any(i not in owned or item_pile(state,i)!='unassigned' for i in remove):
                raise ValueError('First result already used or moved; free retry refused')
            policy=final['policies'][receipt['policy_hash']];number=1
        else:raise ValueError('Unknown exchange operation')
        first=state.next_instance_id or max(owned_instance_ids(state),default=0)+1
        items=self._draw(receipt,policy,number,first)
        receipt['attempts'].append(dict(items=items,reply_sha256=None))
        result=self._result(receipt,number)
        receipt['attempts'][number]['reply_sha256']=digest(json.dumps(result,separators=(',',':')).encode())
        return result,final,self._delta(football,remove,items)

    def _assert_retired(self,value):
        state=self.football.load(self.identity()['persona_id']);owned=owned_instance_ids(state)
        for r in value['receipts']:
            retired=r['source_ids']+([i['instance_id'] for i in r['attempts'][0]['items']] if len(r['attempts'])==2 else [])
            if any(i in owned or i not in state.retired_instance_ids for i in retired):
                raise ValueError('Consumed exchange ownership reappeared')
        return value

    def request(self,operation,session,*,ids=None,exchange_id=None):
        if type(session) is not str or not session or len(session)>256:raise ValueError('Explicit exchange session required')
        return dict(operation=operation,ids=ids,exchange_id=exchange_id,session_hash=digest(session.encode()),
            policy_hash=digest(encode(self.policy)) if operation=='start' else None)

    @account_locked
    def session_request(self,operation,session):
        """The stock empty-body Retry/End refer to this login's latest offer.

        Keep the final receipt addressable for identical retries after End.
        A new Start supplies source IDs and establishes the next offer.
        """
        if operation not in ('retry','confirm'):raise ValueError('Result operation required')
        request=self.request(operation,session)
        with self.locked():
            value=self._read()
            receipt=next((r for r in reversed(value['receipts']) if r['session_hash']==request['session_hash']),None)
            if receipt is None:raise ValueError('No exchange result for this session')
            request['exchange_id']=receipt['exchange_id']
            return request

    def _recover(self,value):
        if value['prepared'] is not None:
            p=value['prepared'];recover_images(self.account,p['images'],writer=atomic,fault=self.fault)
            value=p['state_after'];atomic(self.path,encode(value))
            if self.fault:self.fault('after_source_commit',0)
        return self._assert_retired(value)

    def _barrier(self):
        for name in ('packs.json','purchases.json','native-seasons.json','free-packs.json','free-coins.json','quick-sells.json'):
            p=self.account/name
            if p.exists():
                v=json.loads(p.read_bytes())
                if v.get('prepared') or (name=='native-seasons.json' and v.get('active_match')):
                    raise ValueError('Finish or recover '+name+' before exchange')

    @account_locked
    def preview(self,request):
        with self.locked():
            value=self._read()
            if value['prepared'] is not None:raise ValueError('Recover pending exchange before preview')
            self._assert_retired(value);self._barrier()
            return self._plan(value,json.loads(self.football.path.read_bytes()),request)[0]

    @account_locked
    def execute(self,request):
        with self.locked():
            value=self._recover(self._read());self._barrier();before=self.football.path.read_bytes()
            result,final,after=self._plan(value,json.loads(before),request)
            if final is None:return result
            intent=copy.deepcopy(value)
            intent['prepared']=dict(transaction_id=str(uuid.uuid4()),request=request,
                images=[dict(name='football.json',before=before.hex(),after=encode(after).hex())],state_after=final)
            self._validate(intent);atomic(self.path,encode(intent))
            if self.fault:self.fault('after_intent',0)
            self._recover(intent)
            return result
