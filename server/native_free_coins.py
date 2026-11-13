"""Captured533 empty-target ApplyCard; isolated FreeCoins231 only, default off.

Ownership does not redeem automatically. Use the existing prepared-image/CAS
recovery mechanism for wallet credit plus retirement, never a match reward ID.
A stock effect certificate is separate from these backend guarantees.
"""
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
from pathlib import Path
import uuid

from .account_transaction import account_locked, atomic, recover_images
from .local_content import ContentCatalog
from .local_consumables import inventory_reference
from .local_football import FootballStore, owned_instance_ids
from .local_packs import PackStore
from .local_profile import ProfileStore, load_profile, validate_credits


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True)+'\n').encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def amount(resource_id):
    row = inventory_reference(resource_id)
    if row['cardsubtype'] != 231:
        raise ValueError('Only supplied FreeCoins231 redemption is mapped')
    coins = row['amount']
    if type(coins) is not int or coins <= 0:
        raise ValueError('Invalid supplied FreeCoins amount')
    return validate_credits(coins)


class FreeCoinsCoordinator:
    def __init__(self, account, *, enabled=False, fault=None):
        if enabled is not True:
            raise ValueError('FreeCoins redemption disabled by default')
        from .store_release import projection_account, selected
        self.account = Path(account).resolve()
        projection_account([self.account/name for name in
            ('profile.json','football.json','content.json','packs.json',
             'seasons.json','definition.json','control.json')])
        self.release_store = selected(self.account)
        self.path = self.account/'free-coins.json'
        if self.path.is_symlink() or (self.path.exists() and self.path.stat().st_nlink != 1):
            raise ValueError('Journal alias refused')
        self.profile = ProfileStore(self.account/'profile.json')
        self.football = FootballStore(self.account/'football.json', ContentCatalog(self.account/'content.json'))
        self.packs = PackStore(self.account/'packs.json')
        self.fault = fault

    def identity(self):
        p = self.profile.load()
        return {'identity_pid':p.identity_pid,'persona_id':p.persona_id,'user_id':p.user_id}

    def _empty(self):
        # Repeated pure previews use a stable prospective account namespace.
        namespace = uuid.uuid5(uuid.NAMESPACE_URL, str(self.account))
        return {'schema':1,'account_id':str(namespace),'account_identity':self.identity(),
                'receipts':[],'prepared':None}

    @contextmanager
    def locked(self):
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                # Same packs->profile ordering as purchases/season coordinator.
                with self.packs.transaction(), self.profile.transaction(), self.football.transaction():
                    yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _validate(self, value):
        if (type(value) is not dict or set(value) !=
            {'schema','account_id','account_identity','receipts','prepared'} or
            type(value['schema']) is not int or value['schema'] != 1 or
            value['account_identity'] != self.identity() or type(value['receipts']) is not list):
            raise ValueError('Wrong FreeCoins journal/account identity')
        namespace = uuid.UUID(value['account_id']); sources = set()
        for receipt in value['receipts']:
            if type(receipt) is not dict or set(receipt) != {
                'reward_id','source_id','resource_id','coins','credits_before','credits_after',
                'profile_before_sha256','profile_after_sha256','football_before_sha256','football_after_sha256'}:
                raise ValueError('Invalid FreeCoins receipt fields')
            source = receipt['source_id']
            if type(source) is not int or not 0 < source <= 0x7fffffffffffffff or source in sources:
                raise ValueError('Invalid/duplicate FreeCoins source')
            sources.add(source)
            if (type(receipt['resource_id']) is not int or type(receipt['coins']) is not int or
                receipt['coins'] != amount(receipt['resource_id']) or
                receipt['reward_id'] != str(uuid.uuid5(namespace, 'free-coins:'+str(source))) or
                validate_credits(receipt['credits_after']) != validate_credits(validate_credits(receipt['credits_before'])+receipt['coins'])):
                raise ValueError('FreeCoins receipt/source amount mismatch')
            for key in ('profile_before_sha256','profile_after_sha256','football_before_sha256','football_after_sha256'):
                h = receipt[key]
                if type(h) is not str or len(h) != 64 or any(c not in '0123456789abcdef' for c in h):
                    raise ValueError('Invalid FreeCoins image checksum')
        if value['prepared'] is not None:
            self._validate_intent(value)
        return value

    def _read(self):
        return self._validate(json.loads(self.path.read_bytes())) if self.path.exists() else self._empty()

    def _retirement(self, football, source):
        state = self.football.decode(football, self.identity()['persona_id'])
        item = next((i for i in state.owned_consumables if i.instance_id == source), None)
        if item is None or source in state.retired_instance_ids:
            raise ValueError('Owned FreeCoins source required')
        coins = amount(item.resource_id)
        after = copy.deepcopy(football)
        after['owned_consumables'] = [i for i in football['owned_consumables'] if i['instance_id'] != source]
        if 'inventory_locations' in after:
            after['inventory_locations'] = [i for i in after['inventory_locations'] if i['instance_id'] != source]
        after['retired_instance_ids'] = sorted(football.get('retired_instance_ids', [])+[source])
        self.football.decode(after, state.persona_id)
        return after, item.resource_id, coins

    def _validate_intent(self, value):
        p = value['prepared']
        if type(p) is not dict or set(p) != {'transaction_id','images','state_after'}:
            raise ValueError('Invalid FreeCoins prepared fields')
        uuid.UUID(p['transaction_id']); final = p['state_after']
        if type(final) is not dict or final.get('prepared') is not None:
            raise ValueError('Nested FreeCoins intent refused')
        self._validate(final)
        if (any(final[k] != value[k] for k in ('schema','account_id','account_identity')) or
            final['receipts'][:-1] != value['receipts'] or len(final['receipts']) != len(value['receipts'])+1):
            raise ValueError('FreeCoins intent cannot rewrite history')
        images = p['images']
        if (type(images) is not list or len(images) != 2 or
            [i.get('name') for i in images] != ['profile.json','football.json'] or
            any(set(i) != {'name','before','after'} for i in images)):
            raise ValueError('Invalid FreeCoins image targets')
        receipt = final['receipts'][-1]
        for image in images:
            prefix = image['name'].split('.')[0]
            for direction in ('before','after'):
                if digest(bytes.fromhex(image[direction])) != receipt[prefix+'_'+direction+'_sha256']:
                    raise ValueError('FreeCoins intent checksum mismatch')
        profile = json.loads(bytes.fromhex(images[0]['before']))
        if {k:profile[k] for k in value['account_identity']} != value['account_identity']:
            raise ValueError('FreeCoins profile image owner mismatch')
        before_coins = validate_credits(profile.get('credits', 0))
        football = json.loads(bytes.fromhex(images[1]['before']))
        expected_football, resource, coins = self._retirement(football, receipt['source_id'])
        if (resource != receipt['resource_id'] or coins != receipt['coins'] or
            before_coins != receipt['credits_before']):
            raise ValueError('FreeCoins intent source mismatch')
        profile['credits'] = validate_credits(before_coins+coins)
        if (json.loads(bytes.fromhex(images[0]['after'])) != profile or
            json.loads(bytes.fromhex(images[1]['after'])) != expected_football):
            raise ValueError('FreeCoins intent changes unrelated state')

    def _recover(self, value):
        if value['prepared'] is not None:
            p = value['prepared']
            # _read/_validate checked complete semantics before any image writes.
            recover_images(self.account, p['images'], writer=atomic, fault=self.fault)
            value = p['state_after']
            atomic(self.path, encode(value))
            if self.fault: self.fault('after_source_commit', 0)
        return self._assert_retired(value)

    def _assert_retired(self, value):
        football = self.football.load(value['account_identity']['persona_id'])
        ids = owned_instance_ids(football)
        for r in value['receipts']:
            if r['source_id'] in ids or r['source_id'] not in football.retired_instance_ids:
                raise ValueError('Redeemed FreeCoins ownership reappeared or retirement lost')
        return value

    def inspect(self):
        """Read-only validation for a quiescent archived backup; never recover."""
        value = self._read()
        if value['prepared'] is not None:
            raise ValueError('Recover pending FreeCoins redemption before backup')
        return self._assert_retired(value)

    @account_locked
    def recover(self):
        with self.locked():
            return self._recover(self._read())

    def _preview(self, value, source):
        if type(source) is not int or not 0 < source <= 0x7fffffffffffffff:
            raise ValueError('Full owned source identity required')
        prior = next((r for r in value['receipts'] if r['source_id'] == source), None)
        if prior is not None:
            return prior, None
        # A prior interrupted purchase/open/season operation owns its images.
        # HTTP reads recover those first; direct tools must refuse a new award
        # rather than spend/credit against partially committed projections.
        for name in ('packs.json','purchases.json','native-seasons.json','free-packs.json','quick-sells.json'):
            path = self.account/name
            if path.exists() and json.loads(path.read_bytes()).get('prepared') is not None:
                raise ValueError('Recover pending '+name+' before FreeCoins redemption')
        profile_bytes = self.profile.path.read_bytes(); football_bytes = self.football.path.read_bytes()
        profile = json.loads(profile_bytes); football = json.loads(football_bytes)
        if self.release_store:
            from .local_football import item_pile
            if item_pile(self.football.load(1), source) != 'unassigned':
                raise ValueError('Only certified unassigned Redeem Item is deployed')
        after_football, resource, coins = self._retirement(football, source)
        before_coins = validate_credits(profile.get('credits', 0))
        profile['credits'] = validate_credits(before_coins+coins)
        after_profile = encode(profile); after_bytes = encode(after_football)
        receipt = {'reward_id':str(uuid.uuid5(uuid.UUID(value['account_id']), 'free-coins:'+str(source))),
            'source_id':source,'resource_id':resource,'coins':coins,
            'credits_before':before_coins,'credits_after':profile['credits'],
            'profile_before_sha256':digest(profile_bytes),'profile_after_sha256':digest(after_profile),
            'football_before_sha256':digest(football_bytes),'football_after_sha256':digest(after_bytes)}
        return receipt, [
            {'name':'profile.json','before':profile_bytes.hex(),'after':after_profile.hex()},
            {'name':'football.json','before':football_bytes.hex(),'after':after_bytes.hex()}]

    @account_locked
    def preview(self, source):
        with self.locked():
            value = self._read()
            if value['prepared'] is not None:
                raise ValueError('Recover pending FreeCoins intent before preview')
            self._recover(value)
            return self._preview(value, source)[0]

    @account_locked
    def redeem(self, source):
        with self.locked():
            value = self._recover(self._read())
            receipt, images = self._preview(value, source)
            if images is None: return receipt
            final = copy.deepcopy(value); final['receipts'].append(receipt)
            intent = copy.deepcopy(value)
            intent['prepared'] = {'transaction_id':str(uuid.uuid4()),'images':images,'state_after':final}
            self._validate(intent)
            atomic(self.path, encode(intent))
            if self.fault: self.fault('after_intent', 0)
            self._recover(intent)
            return receipt
