"""Recoverable single/bulk quick sell using the existing FreeCoins coordinator.

Reuses its account identity, lock order, prepared-image/CAS recovery and public
preview/redeem sequence. Only selection validation and the operation's semantic
delta differ: exact unassigned ownership retirement plus one quoted coin credit.
"""
import copy,json,uuid
from pathlib import Path
from .native_free_coins import FreeCoinsCoordinator,encode,digest
from .local_football import item_pile,owned_instance_ids
from .local_profile import validate_credits
from .quick_sell_policy import quote,policy


def selection(ids):
    if (type(ids) not in (tuple,list) or not 1<=len(ids)<=100 or
        any(type(i) is not int or not 0<i<=0x7fffffffffffffff for i in ids) or len(set(ids))!=len(ids)):
        raise ValueError('Invalid/duplicate quick-sell selection')
    return tuple(sorted(ids))


class QuickSellCoordinator(FreeCoinsCoordinator):
    def __init__(self,account,*,enabled=False,fault=None):
        super().__init__(account,enabled=enabled,fault=fault)
        self.path=self.account/'quick-sells.json'
        if self.path.is_symlink() or (self.path.exists() and self.path.stat().st_nlink!=1):
            raise ValueError('Quick-sell journal alias refused')

    def _retirement(self,football,ids):
        state=self.football.decode(football,1);ids=selection(ids)
        owned={i.instance_id:i for i in state.owned_items+state.owned_consumables+state.owned_club_items}
        from .club_item_actions import quick_sell_enabled
        piles=('unassigned','club','trade') if quick_sell_enabled(self.football) else ('unassigned',)
        if any(i not in owned or item_pile(state,i) not in piles for i in ids):
            raise ValueError('Only owned admitted quick-sell sources')
        from .market_protocol import escrowed
        if set(ids)&escrowed(self.football.path.parent):raise ValueError('Listed item is in escrow')
        if any(s.instance_id in ids for s in state.active_lineup):raise ValueError('Active player cannot be sold')
        if any(s.instance_id in ids for squad in state.other_squads for s in squad.lineup):
            raise ValueError('Remove player from saved squads before quick sell')
        quotes=[quote(owned[i],untradeable=i in state.untradeable_instance_ids) for i in ids]
        after=copy.deepcopy(football)
        for name in ('owned_items','owned_consumables','owned_club_items','inventory_locations'):
            if name in football:after[name]=[i for i in football[name] if i['instance_id'] not in ids]
        after['retired_instance_ids']=sorted(football.get('retired_instance_ids',[])+list(ids))
        self.football.decode(after,1)
        return after,quotes

    def _validate(self,value):
        if (type(value) is not dict or set(value)!={'schema','account_id','account_identity','receipts','prepared'} or
            type(value['schema']) is not int or value['schema']!=1 or value['account_identity']!=self.identity() or
            type(value['receipts']) is not list):raise ValueError('Invalid quick-sell journal/account')
        namespace=uuid.UUID(value['account_id']);sold=set();_,sha=policy()
        for r in value['receipts']:
            if type(r) is not dict or set(r)!={'reward_id','source_ids','items','coins','credits_before','credits_after',
                    'profile_before_sha256','profile_after_sha256','football_before_sha256','football_after_sha256'}:
                raise ValueError('Invalid quick-sell receipt fields')
            ids=selection(r['source_ids'])
            if list(ids)!=r['source_ids'] or sold.intersection(ids):raise ValueError('Conflicting quick-sell retirement')
            sold.update(ids)
            if r['reward_id']!=str(uuid.uuid5(namespace,'quick-sell:'+','.join(map(str,ids)))):
                raise ValueError('Invalid quick-sell reward identity')
            if type(r['items']) is not list or len(r['items'])!=len(ids):raise ValueError('Invalid quoted selection')
            from .local_football import OwnedPlayerItem,OwnedConsumableItem,OwnedClubItem
            for iid,item in zip(ids,r['items']):
                if item.get('instance_id')!=iid:raise ValueError('Quick-sell selection changed')
                if item.get('kind')!='club' and item.get('policy_sha256')!=sha:raise ValueError('Quick-sell policy changed')
                if item['kind']=='player':source=OwnedPlayerItem(iid,item['resource_id'],special_version_id=item['special_version_id'])
                elif item['kind']=='consumable' and item['special_version_id'] is None:source=OwnedConsumableItem(iid,item['resource_id'])
                elif item['kind']=='club' and item['special_version_id'] is None:source=OwnedClubItem(iid,item['resource_id'],item['item_type'])
                else:raise ValueError('Invalid quick-sell source kind')
                if quote(source,untradeable=item.get('untradeable',False))!=item:raise ValueError('Quick-sell quote changed')
            if (type(r['coins']) is not int or r['coins']!=sum(i['coins'] for i in r['items']) or
                validate_credits(r['credits_after'])!=validate_credits(validate_credits(r['credits_before'])+r['coins'])):
                raise ValueError('Quick-sell wallet receipt mismatch')
            for name in ('profile_before_sha256','profile_after_sha256','football_before_sha256','football_after_sha256'):
                h=r[name]
                if type(h) is not str or len(h)!=64 or any(c not in '0123456789abcdef' for c in h):raise ValueError('Invalid quick-sell image digest')
        if value['prepared'] is not None:
            p=value['prepared']
            if type(p) is not dict or set(p)!={'transaction_id','images','state_after'}:raise ValueError('Invalid quick-sell intent')
            uuid.UUID(p['transaction_id']);final=p['state_after']
            if final.get('prepared') is not None:raise ValueError('Nested quick-sell intent')
            self._validate(final)
            if (any(final[k]!=value[k] for k in ('schema','account_id','account_identity')) or
                final['receipts'][:-1]!=value['receipts'] or len(final['receipts'])!=len(value['receipts'])+1):
                raise ValueError('Quick-sell intent rewrites history')
            images=p['images'];r=final['receipts'][-1]
            if (type(images) is not list or len(images)!=2 or [i.get('name') for i in images]!=['profile.json','football.json'] or
                any(set(i)!={'name','before','after'} for i in images)):raise ValueError('Invalid quick-sell image targets')
            for image in images:
                for d in ('before','after'):
                    if digest(bytes.fromhex(image[d]))!=r[image['name'].split('.')[0]+'_'+d+'_sha256']:
                        raise ValueError('Quick-sell image checksum mismatch')
            before_profile=json.loads(bytes.fromhex(images[0]['before']))
            if {k:before_profile[k] for k in value['account_identity']}!=value['account_identity']:
                raise ValueError('Quick-sell profile owner mismatch')
            after_football,quotes=self._retirement(json.loads(bytes.fromhex(images[1]['before'])),r['source_ids'])
            if quotes!=r['items'] or before_profile.get('credits',0)!=r['credits_before']:
                raise ValueError('Quick-sell intent source/quote mismatch')
            before_profile['credits']=r['credits_after']
            if [before_profile,after_football]!=[json.loads(bytes.fromhex(i['after'])) for i in images]:
                raise ValueError('Quick-sell intent changes unrelated state')
        return value

    def _assert_retired(self,value):
        state=self.football.load(1);owned=owned_instance_ids(state)
        for r in value['receipts']:
            if any(i in owned or i not in state.retired_instance_ids for i in r['source_ids']):
                raise ValueError('Sold ownership reappeared/retirement lost')
        return value

    def inspect(self):
        value=self._read()
        if value['prepared'] is not None:raise ValueError('Recover pending QuickSell transaction before backup')
        return self._assert_retired(value)

    def _preview(self,value,source):
        ids=selection(source)
        prior=next((r for r in value['receipts'] if r['source_ids']==list(ids)),None)
        if prior:return prior,None
        for name in ('packs.json','purchases.json','native-seasons.json','free-coins.json','free-packs.json'):
            path=self.account/name
            if path.exists() and json.loads(path.read_bytes()).get('prepared'):
                raise ValueError('Recover pending '+name+' before quick sell')
        profile_bytes=self.profile.path.read_bytes();football_bytes=self.football.path.read_bytes()
        profile=json.loads(profile_bytes);football=json.loads(football_bytes)
        after_football,quotes=self._retirement(football,ids);coins=sum(q['coins'] for q in quotes)
        before=validate_credits(profile.get('credits',0));profile['credits']=validate_credits(before+coins)
        p,f=encode(profile),encode(after_football)
        receipt={'reward_id':str(uuid.uuid5(uuid.UUID(value['account_id']),'quick-sell:'+','.join(map(str,ids)))),
            'source_ids':list(ids),'items':quotes,'coins':coins,'credits_before':before,'credits_after':profile['credits'],
            'profile_before_sha256':digest(profile_bytes),'profile_after_sha256':digest(p),
            'football_before_sha256':digest(football_bytes),'football_after_sha256':digest(f)}
        return receipt,[{'name':'profile.json','before':profile_bytes.hex(),'after':p.hex()},
                        {'name':'football.json','before':football_bytes.hex(),'after':f.hex()}]
