"""Explicit revival_policy definitions, selection and crash-safe consumption.

Catalog/odds are local policy. The captured stock opening contract is separate
in pack_protocol. State stores only entitlements and owned-ID/resource receipts.
"""
import json, os, tempfile, fcntl, hashlib, math, uuid
from dataclasses import asdict,dataclass
from pathlib import Path
from contextlib import contextmanager

from .pack_policy import load_definitions
DEFINITIONS = load_definitions()

def receipt_items(receipt):
    """Typed allocation records; old player receipts retain their schema."""
    from .local_football import OwnedPlayerItem,OwnedConsumableItem,OwnedClubItem
    cls=OwnedConsumableItem if DEFINITIONS[receipt['definition']].get('item_family')=='consumable' else OwnedPlayerItem
    if (DEFINITIONS[receipt['definition']].get('item_family') in ('mixed_bronze','mixed_silver','mixed_gold') or
        DEFINITIONS[receipt['definition']].get('selection')=='typed_tier_quota_v1'):
        return tuple((OwnedClubItem if 'item_type' in r else OwnedConsumableItem if set(r)=={'instance_id','resource_id'} else OwnedPlayerItem)(**r) for r in receipt['items'])
    return tuple(cls(**row) for row in receipt['items'])

def player_formation(catalog_id,resource_id):
    """Reproducible pseudorandom draw from the17 original-client formations.

    Revival policy, not recovered historical odds. Chosen once at allocation,
    persisted with the owned item; never rerolled on startup or rendering.
    """
    from .local_formations import FORMATIONS
    choices=tuple(sorted(FORMATIONS))
    digest=hashlib.sha256(f'revival_policy:player-formation:{catalog_id}:{resource_id}'.encode()).digest()
    return choices[int.from_bytes(digest,'big')%len(choices)]

def select_cards(definition,catalog_id,*,private_identity_version=None):
    from .card_pool import gold_pool
    if definition not in DEFINITIONS:raise ValueError('Unknown revival definition')
    rule=DEFINITIONS[definition]
    if rule.get('selection') == 'specific_supplied_consumable_v1':
        from .store_single_consumables import select_resource
        return select_resource(
            rule, catalog_id, private_identity_version=private_identity_version,
        )
    if rule.get('selection') == 'reviewed_tier_special_v1':
        return tuple(
            pull.resource_id for pull in select_pulls(
                definition, catalog_id,
                private_identity_version=private_identity_version,
            )
        )
    if rule.get('selection')=='typed_tier_quota_v1':return tuple(p.resource_id for p in select_pulls(definition,catalog_id,private_identity_version=private_identity_version))
    if rule.get('selection')=='consumables_tier_quota_v1':
        from .specialist_consumable_packs import select_resources
        return select_resources(definition,catalog_id,rule,private_identity_version=private_identity_version)
    if rule.get('item_family') in ('mixed_bronze','mixed_silver','mixed_gold'):
        return tuple(c.resource_id for c in mixed_tier_pulls(definition,catalog_id))
    if rule['selection']=='reviewed_specials_sha256_without_replacement':
        return tuple(c.resource_id for c in select_pulls(definition,catalog_id,private_identity_version=private_identity_version))
    if rule['selection']=='reconstructed_special_test':
        from .reconstructed_specials import version
        selected=tuple(version(key) for key in rule['special_versions'])
        if any(v.pack_eligibility['base_quality']!=rule['quality'] for v in selected):raise ValueError('Pack family must follow original/base quality')
        return tuple(v.base_resource_id for v in selected)
    if rule['selection']=='weighted_sha256_without_replacement':
        if rule.get('item_family')=='consumable':
            from .local_consumables import references
            pool=[(r['carddbid'],int(r['weightrare']>0)) for r in references().values() if r['cardsubtype'] in rule['subtypes']]
        else:pool=[(c.resource_id,c.rare) for c in gold_pool()]
        def score(card):
            digest=hashlib.sha256(f'revival_policy:{definition}:{catalog_id}:{card[0]}'.encode()).digest()
            u=(int.from_bytes(digest[:8],'big')+1)/(2**64+1)
            return -math.log(u)/rule['weights']['rare' if card[1] else 'common'],card[0]
        ordered=sorted(pool,key=score)
        rare=[c for c in ordered if c[1]][:rule['minimum_rare']]
        remainder=[c for c in ordered if c not in rare and (not rule.get('exact_rare') or not c[1])]
        chosen=rare+remainder[:rule['item_count']-len(rare)]
        if len(rare)!=rule['minimum_rare'] or len(chosen)!=rule['item_count']:raise ValueError('Insufficient eligible policy pool')
        return tuple(c[0] for c in chosen)
    if rule.get('item_family')=='consumable':
        from .local_consumables import references
        rows=references().values()
        selected=tuple(min(row['carddbid'] for row in rows if row['cardsubtype']==subtype) for subtype in rule['subtypes'])
        if len(set(selected))!=rule['item_count']:raise ValueError('Invalid consumable selection')
        return selected
    ordered=sorted(gold_pool(),key=lambda card:hashlib.sha256(
        f'revival_policy:{definition}:{catalog_id}:{card.resource_id}'.encode()).digest())
    rare=[card for card in ordered if card.rare==1][:rule['minimum_rare']]
    selected=rare+[card for card in ordered if card.resource_id not in {r.resource_id for r in rare}][:rule['item_count']-len(rare)]
    if len(selected)!=rule['item_count'] or len(rare)!=rule['minimum_rare']:raise ValueError('Insufficient eligible pool')
    return tuple(card.resource_id for card in selected)

@dataclass(frozen=True)
class PlayerPull:
    resource_id:int
    special_version_id:str|None=None
    base_rare:int=0
    base_quality:str='gold'

@dataclass(frozen=True)
class MixedPull(PlayerPull):
    item_family:str='player'

def mixed_tier_pool(tier,include_tier_specials=False,consumable_pool='training_v1',club_item_pool=None):
    if tier not in ('bronze','silver','gold'):raise ValueError('Unsupported mixed tier')
    from .card_pool import card_index
    from .local_consumables import pack_references
    def quality(rating):return 'gold' if rating>=75 else 'silver' if rating>=65 else 'bronze'
    players=tuple(MixedPull(c.resource_id,None,c.rare,tier) for c in card_index().values() if c.quality==tier and c.lookup_supported)
    if tier=='gold' or include_tier_specials:
        from .reconstructed_specials import reviewed_pool
        players+=tuple(MixedPull(v.base_resource_id,v.record_id,v.pack_eligibility['base_rare'],v.pack_eligibility['base_quality']) for v in reviewed_pool(tier if include_tier_specials else None))
    consumables=tuple(MixedPull(rid,None,int(r['weightrare']>0),quality(r['rating']),'consumable') for rid,r in pack_references(consumable_pool).items())
    club=()
    if club_item_pool is not None:
        from .local_club_items import POOL,references,quality as club_quality
        if club_item_pool!=POOL:raise ValueError('Unknown club-item pack pool')
        club=tuple(MixedPull(rid,None,r['rare'],club_quality(r),r['item_type']) for rid,r in references().items())
    return players+consumables+club

def mixed_bronze_pool():
    return mixed_tier_pool('bronze')

def mixed_counts_rare(card,rule):
    return bool(card.base_rare or (rule.get('specials_satisfy_rare_guarantee',False) and card.special_version_id))

def mixed_rank(tier,definition,catalog_id,card,include_tier_specials=False):
    seed=f'mixed_{tier}_v1:{definition}:{catalog_id}:{card.item_family}:{card.resource_id}'
    # Gold admits multiple versions of the same base. Rank each independently;
    # keep the physically certified Bronze and prior Silver seeds byte-identical.
    if tier=='gold' or include_tier_specials:seed+=':'+str(card.special_version_id or 'base')
    return hashlib.sha256(seed.encode()).digest()

def mixed_tier_pulls(definition,catalog_id):
    rule=DEFINITIONS[definition];tier=rule['quality'];tier_specials=rule['selection']==f'mixed_{tier}_all_specials_v1';pool=mixed_tier_pool(tier,tier_specials,rule.get('consumable_pool','training_v1'),rule.get('club_item_pool'))
    from .pack_draw_cache import selected
    from .pack_special_rates import rates_for
    rates = rates_for(rule)
    return selected(('mixed_tier_v1',mixed_rank,mixed_counts_rare),
        (definition,catalog_id,rates),rule,pool,
        lambda:_select_mixed_tier(definition,catalog_id,rule,tier,tier_specials,pool))

def _select_mixed_tier(definition,catalog_id,rule,tier,tier_specials,pool):
    ordered=sorted(pool,key=lambda c:mixed_rank(tier,definition,catalog_id,c,tier_specials))
    # Random type ratio and exact rarity/tier bounds are revival selection,
    # not recovered EA odds. Large Gold policies use the same supplied pool.
    chosen=[];higher=0
    from .pack_special_rates import rates_for, probabilities, pick, slot_rare
    rates = rates_for(rule)
    chances = probabilities(pool, rates) if rates else None
    for rarity,count in ((1,rule['minimum_rare']),(0,rule['item_count']-rule['minimum_rare'])):
        selected=[]
        if rates:
            # pack_special_rates_v1: specials follow their base rarity; each
            # slot decides special-or-not first.
            def usable(card, picked):
                if card.resource_id in {c.resource_id for c in chosen + picked}:
                    return False
                extra = sum(c.base_quality != tier for c in picked)
                return card.base_quality == tier or higher + extra < rule['item_count'] - rule['minimum_' + tier]
            ranked = [c for c in ordered if slot_rare(c) == bool(rarity)]
            seed = f'{definition}:{catalog_id}:{tier}:{rarity}'
            selected = pick(ranked, count, chances[tier, bool(rarity)], seed, usable)
            higher += sum(c.base_quality != tier for c in selected)
            if len(selected) != count:
                raise ValueError('Insufficient mixed ' + tier + ' pool')
            chosen.extend(selected)
            continue
        for card in ordered:
            if mixed_counts_rare(card,rule)!=rarity or card.resource_id in {c.resource_id for c in chosen+selected}:continue
            if card.base_quality!=tier and higher>=rule['item_count']-rule['minimum_'+tier]:continue
            selected.append(card);higher+=card.base_quality!=tier
            if len(selected)==count:break
        if len(selected)!=count:raise ValueError('Insufficient mixed '+tier+' pool')
        chosen.extend(selected)
    return tuple(sorted(chosen,key=lambda c:ordered.index(c)))

def mixed_bronze_pulls(definition,catalog_id):
    if DEFINITIONS[definition]['quality']!='bronze':raise ValueError('Not a Bronze definition')
    return mixed_tier_pulls(definition,catalog_id)

def allocated_items(pulls,first,key,rule):
    from .local_football import OwnedPlayerItem,OwnedConsumableItem,OwnedClubItem
    return tuple(OwnedConsumableItem(first+n,p.resource_id) if getattr(p,'item_family','player')=='consumable' else
        OwnedClubItem(first+n,p.resource_id,p.item_family) if getattr(p,'item_family','player') in ('badge','kit','stadium','ball') else
        OwnedPlayerItem(first+n,p.resource_id,rule['new_player_fitness'],player_formation(key,p.resource_id),special_version_id=p.special_version_id)
        for n,p in enumerate(pulls))


def reviewed_player_pool(quality,families=('totw',)):
    """Base and reviewed versions are independent candidates, tiered by base."""
    from .card_pool import card_index
    from .reconstructed_specials import reviewed_pool
    if quality not in ('gold','silver','bronze','mixed'):raise ValueError('Unknown player pool quality')
    # Mixed Specials keeps proven ordinary Gold fillers, with admitted special
    # versions from every original base tier. Special OVR never rebuckets bases.
    ordinary_quality='gold' if quality=='mixed' else quality
    special_quality=None if quality=='mixed' else quality
    ordinary=tuple(PlayerPull(c.resource_id,None,c.rare,c.quality) for c in card_index().values()
                   if c.lookup_supported and c.quality==ordinary_quality)
    special=tuple(PlayerPull(v.base_resource_id,v.record_id,v.pack_eligibility['base_rare'],
                            v.pack_eligibility['base_quality']) for v in reviewed_pool(special_quality,families))
    return ordinary+special


def select_pulls(definition,catalog_id,*,private_identity_version=None):
    """Typed choices retain version identity throughout preparation and commit."""
    rule=DEFINITIONS[definition]
    if rule.get('selection') == 'specific_supplied_consumable_v1':
        resources = select_cards(
            definition, catalog_id, private_identity_version=private_identity_version,
        )
        return tuple(MixedPull(
            resource_id=resource_id, base_rare=rule['minimum_rare'],
            base_quality=rule['quality'], item_family='consumable',
        ) for resource_id in resources)
    if rule.get('selection') == 'reviewed_tier_special_v1':
        from .tournament_special_packs import select_pulls as select_special
        return select_special(
            definition, catalog_id, rule,
            private_identity_version=private_identity_version,
        )
    if rule.get('selection')=='typed_tier_quota_v1':
        from .standard_pack_specs import select_pulls as select_typed
        return select_typed(definition,catalog_id,rule,private_identity_version=private_identity_version)
    if rule.get('item_family') in ('mixed_bronze','mixed_silver','mixed_gold'):return mixed_tier_pulls(definition,catalog_id)
    if rule['selection']!='reviewed_specials_sha256_without_replacement':
        resources=select_cards(definition,catalog_id,private_identity_version=private_identity_version)
        return tuple(PlayerPull(rid,(rule.get('special_versions') or [None]*len(resources))[n])
                     for n,rid in enumerate(resources))
    pools={'reviewed_totw3':('totw',),'reviewed_tots11':('tots',),'reviewed_all_admitted':None}
    pool=reviewed_player_pool(rule['quality'],pools[rule['special_pool']])
    if 'nationality' in rule:
        # STORE-006: base and special versions follow the supplied player's nationality.
        from .card_pool import card_index
        from .tournament_starter_facts import player_facts
        index=card_index()
        pool=tuple(c for c in pool if player_facts(index[c.resource_id].player_id)[0]==rule['nationality'])
    from .pack_special_rates import rates_for, special_weight_multipliers
    rates=rates_for(rule)
    # pack_special_rates_v1: specials weighted to the per-slot target instead of special_weight.
    factors=special_weight_multipliers(pool,rates) if rates else None
    def score(card):
        identity=f'{card.resource_id}:{card.special_version_id or "base"}'
        digest=hashlib.sha256(f'revival_policy:{definition}:{catalog_id}:{identity}'.encode()).digest()
        u=(int.from_bytes(digest[:8],'big')+1)/(2**64+1)
        weight=rule['weights']['rare' if card.base_rare else 'common']
        if card.special_version_id:
            weight*=float(factors.get((card.base_quality,bool(card.base_rare)),0)) if factors else rule['special_weight']
        if weight<=0:return float('inf'),identity
        return -math.log(u)/weight,identity
    ordered=sorted(pool,key=score)
    n=rule['item_count'];ns=rule['minimum_special'];nr=rule['minimum_rare']
    def counts_rare(card):
        # pack_special_rates_v1: a special fills the slot kind of its base card.
        if rates:return bool(card.base_rare)
        # Explicit new Gold-pack policy: an admitted special satisfies a rare
        # slot, without rewriting its preserved ordinary base rarity.
        return bool(card.base_rare or (rule.get('specials_satisfy_rare_guarantee',False) and card.special_version_id))
    def guaranteed_special(card):
        if not card.special_version_id:return False
        family=rule.get('guaranteed_special_family')
        if family is None:return True
        from .reconstructed_specials import version
        return version(card.special_version_id).family==family
    # Reserve enough rare specials to allow both overlapping guarantees. A
    # Default historical definitions use base rarity. Versioned Gold rotation
    # definitions explicitly allow admitted specials to satisfy rare slots.
    must_rare_special=max(0,nr-(n-ns))
    chosen=[]
    def take(candidates,count):
        # Preserve the existing one-base-resource-per-pack guarantee. Base and
        # special versions still have independent pool entries and may coexist
        # in ownership/across openings; no draw suppresses either globally.
        taken=0
        for c in candidates:
            if taken>=count:break
            if c.resource_id in {i.resource_id for i in chosen}:continue
            chosen.append(c);taken+=1
        return taken
    if take([c for c in ordered if guaranteed_special(c) and counts_rare(c)],must_rare_special)!=must_rare_special:
        raise ValueError('Insufficient rare special pool')
    take([c for c in ordered if guaranteed_special(c)],ns-len(chosen))
    if len(chosen)!=ns:raise ValueError('Insufficient reviewed special pool')
    needed=nr-sum(counts_rare(c) for c in chosen)
    take([c for c in ordered if counts_rare(c)],max(0,needed))
    take([c for c in ordered if not rule.get('exact_rare') or not counts_rare(c)],n-len(chosen))
    if len(chosen)!=n or sum(counts_rare(c) for c in chosen)<nr or (rule.get('exact_rare') and sum(counts_rare(c) for c in chosen)!=nr) or sum(guaranteed_special(c) for c in chosen)<ns:
        raise ValueError('Unsatisfied reviewed pack guarantee')
    return tuple(chosen)

_LOAD_CACHE={}


class PackStore:
    def __init__(self,path): self.path=Path(path)
    def load(self,persona=1):
        #PERF (GAME-012 slow-load finding): full receipt re-derivation is a pure
        #function of these exact bytes and process-static catalogs. Memoize the
        #validated value by content hash; callers always receive a deep copy and
        #invalid states are never cached (they raise every time).
        if not self.path.exists(): return {'persona_id':persona,'next_catalog_id':30001,'entitlements':[],'consumed':[]}
        import copy,hashlib
        from .draw_seal import fingerprint as seal_fingerprint
        raw=self.path.read_bytes();key=(str(self.path.resolve()),persona,hashlib.sha256(raw).digest(),seal_fingerprint(self.path.parent))
        hit=_LOAD_CACHE.get(key)
        if hit is None:
            hit=self._validated(raw,persona)
            if len(_LOAD_CACHE)>=8:_LOAD_CACHE.clear()
            _LOAD_CACHE[key]=hit
        return copy.deepcopy(hit)
    def _validated(self,raw,persona):
        value=json.loads(raw.decode())
        if (set(value)-{'persona_id','next_catalog_id','entitlements','consumed','prepared','source_grants','voucher_grants','identity_version'} or
            not {'persona_id','next_catalog_id','entitlements','consumed'}<=set(value) or
            type(value['persona_id']) is not int or value['persona_id']!=persona or
            type(value['entitlements']) is not list or type(value['consumed']) is not list):
            raise ValueError('Invalid pack account')
        from .native_pack_sessions import PRIVATE_VERSION,PRIVATE_MAX
        if 'identity_version' in value and value['identity_version']!=PRIVATE_VERSION:raise ValueError('Invalid private pack identity version')
        limit=PRIVATE_MAX if value.get('identity_version')==PRIVATE_VERSION else 65535
        ids=[]
        for record in value['entitlements']:
            if (set(record)-{'untradeable'}!={'catalog_id','definition','provenance'} or
                ('untradeable' in record and record['untradeable'] is not True) or record['definition'] not in DEFINITIONS
                or record['provenance']!='revival_policy' or type(record['catalog_id']) is not int
                or not 30001<=record['catalog_id']<=limit): raise ValueError('Invalid entitlement')
            ids.append(record['catalog_id'])
        for receipt in value['consumed']+([value['prepared']] if value.get('prepared') else []):
            if (set(receipt)-{'untradeable','opening_identity','draw_version'}!={'catalog_id','definition','provenance','items'} or
                ('untradeable' in receipt and receipt['untradeable'] is not True) or
                receipt['definition'] not in DEFINITIONS or receipt['provenance']!='revival_policy' or
                type(receipt['catalog_id']) is not int or not 30001<=receipt['catalog_id']<=limit):
                raise ValueError('Invalid consumption receipt')
            if 'draw_version' in receipt and (type(receipt['draw_version']) is not int or receipt['draw_version'] != 2):
                raise ValueError('Invalid pack draw version')
            selection_key = self.selection_key(receipt['catalog_id'], receipt.get('draw_version'))
            if 'opening_identity' in receipt:
                ident=receipt['opening_identity']
                if (type(ident) is not dict or set(ident)!={'sid','wire_id'} or type(ident['sid']) is not str or not ident['sid'].startswith('fifa16-pack-') or len(ident['sid'])!=44 or type(ident['wire_id']) is not int or not 1<=ident['wire_id']<=65535):raise ValueError('Invalid native opening identity')
            from .local_football import OwnedPlayerItem
            items=receipt_items(receipt)
            if len(items)!=DEFINITIONS[receipt['definition']]['item_count'] or len({item.instance_id for item in items})!=len(items):
                raise ValueError('Invalid receipt identities/count')
            if (DEFINITIONS[receipt['definition']].get('item_family') in ('mixed_bronze','mixed_silver','mixed_gold') or
                DEFINITIONS[receipt['definition']].get('selection')=='typed_tier_quota_v1'):
                from .local_football import OwnedConsumableItem,OwnedClubItem
                from .draw_seal import is_sealed
                # Sealed history (draw_seal): verified by exact digest, not re-drawn from today's pool.
                sealed=receipt in value['consumed'] and is_sealed(self.path.parent,'packs',receipt['catalog_id'],receipt)
                expected=None if sealed else select_pulls(receipt['definition'],selection_key,private_identity_version=value.get('identity_version'))
                if not sealed and [(i.resource_id,i.item_type if type(i) is OwnedClubItem else 'consumable' if type(i) is OwnedConsumableItem else 'player',getattr(i,'special_version_id',None)) for i in items]!=[(i.resource_id,i.item_family,i.special_version_id) for i in expected]:
                    raise ValueError('Mixed receipt differs from pinned catalog draw')
                if any(type(i) is OwnedPlayerItem and (i.fitness!=99 or i.morale!=99 or i.formation_id!=player_formation(receipt['catalog_id'],i.resource_id)) for i in items):raise ValueError('Mixed initial player state differs from pinned allocation')
            from .local_content import ContentCatalog
            for item in items:
                if type(item.instance_id) is not int or not 0<item.instance_id<=0x7fffffffffffffff:raise ValueError('Invalid receipt identity')
                from .local_football import OwnedConsumableItem,OwnedClubItem
                if type(item) is OwnedClubItem:
                    from .local_club_items import reference
                    if DEFINITIONS[receipt['definition']].get('club_item_pool') is None:raise ValueError('Club item in historical pack receipt')
                    reference(item.item_type,item.resource_id)
                    continue
                if type(item) is OwnedConsumableItem:
                    if DEFINITIONS[receipt['definition']].get('selection') == 'specific_supplied_consumable_v1':
                        expected = select_cards(
                            receipt['definition'], selection_key,
                            private_identity_version=value.get('identity_version'),
                        )
                        if tuple(i.resource_id for i in items) != expected:
                            raise ValueError('Specific consumable receipt differs from purchased card')
                        continue
                    if DEFINITIONS[receipt['definition']].get('selection')=='typed_tier_quota_v1':
                        from .local_consumables import inventory_reference
                        inventory_reference(item.resource_id)
                        continue
                    if DEFINITIONS[receipt['definition']].get('selection')=='consumables_tier_quota_v1':
                        if tuple(i.resource_id for i in items)!=select_cards(receipt['definition'],selection_key,private_identity_version=value.get('identity_version')):
                            raise ValueError('Specialist consumable receipt differs from pinned draw')
                        continue
                    if DEFINITIONS[receipt['definition']].get('item_family') in ('mixed_bronze','mixed_silver','mixed_gold'):
                        from .local_consumables import inventory_reference
                        inventory_reference(item.resource_id)
                        continue
                    from .local_consumables import reference
                    if reference(item.resource_id)['cardsubtype'] not in DEFINITIONS[receipt['definition']]['subtypes']:
                        raise ValueError('Incompatible pack consumable')
                    continue
                ContentCatalog().get(item.resource_id)
                from .reconstructed_specials import validate_reference
                validate_reference(item)
                from .local_formations import FORMATIONS
                if (type(item.fitness) is not int or not 1<=item.fitness<=99 or
                    (item.formation_id is not None and (type(item.formation_id) is not int or item.formation_id not in FORMATIONS))):
                    raise ValueError('Invalid initial pack-item condition')
            if receipt in value['consumed']:ids.append(receipt['catalog_id'])
        if value.get('prepared') and value['prepared']['catalog_id'] not in [e['catalog_id'] for e in value['entitlements']]:
            raise ValueError('Prepared receipt lacks entitlement')
        if len(set(ids))!=len(ids) or type(value['next_catalog_id']) is not int or not max(ids,default=30000)<value['next_catalog_id']<=limit+1:
            raise ValueError('Invalid pack catalog allocator')
        openings=[(r['opening_identity']['sid'],r['opening_identity']['wire_id']) for r in value['consumed']+([value['prepared']] if value.get('prepared') else []) if 'opening_identity' in r]
        if len(set(openings))!=len(openings):raise ValueError('Duplicate native opening identity')
        sources=value.get('source_grants',[])
        if type(sources) is not list:raise ValueError('Invalid source pack grants')
        keys=set();owners=set();catalogs=set()
        for source in sources:
            required={'reward_id','source_id','source_kind','account_id','persona_id','cycle_id',
                      'policy_version','certification','entitlement'}
            if type(source) is not dict or set(source)!=required:raise ValueError('Invalid pack source receipt')
            # XP-004 level-up and ACCOMP-001 packs use their own kind and policy, never fixture/season.
            level_source = source['source_kind'] == 'level'
            accomplishment_source = source['source_kind'] == 'accomplishment'
            setup_source = source['source_kind'] == 'setup'
            if (source['source_kind'] not in ('fixture','season','level','accomplishment','setup') or type(source['persona_id']) is not int or
                source['persona_id']!=persona or source['policy_version'] not in ('backend_pack_entitlement_test_v1','reward_store_parity_v1','tournament_rewards_v2','level_rewards_v1','accomplishments_v1','first_run_v1') or
                level_source != (source['policy_version'] == 'level_rewards_v1') or
                accomplishment_source != (source['policy_version'] == 'accomplishments_v1') or
                setup_source != (source['policy_version'] == 'first_run_v1') or
                source['certification']!='backend_only'):raise ValueError('Invalid pack source ownership/policy')
            for name in ('source_id','account_id','cycle_id'):uuid.UUID(source[name])
            key=(source['source_kind'],source['source_id'])
            if source['reward_id']!=str(uuid.uuid5(uuid.UUID(source['source_id']),source['source_kind']+'-pack')) or key in keys:
                raise ValueError('Duplicate or invalid pack reward identity')
            e=source['entitlement']
            if type(e) is not dict:raise ValueError('Invalid source entitlement')
            owned=next((r for r in value['entitlements']+value['consumed'] if r['catalog_id']==e.get('catalog_id')),None)
            expected_keys={'catalog_id','definition','provenance'}
            if source['policy_version']=='reward_store_parity_v1':
                from .reward_store_parity import policy
                expected_keys.add('untradeable')
                if e.get('untradeable') is not True or e.get('definition') not in {r['definition'] for r in policy()['bindings'].values()}:
                    raise ValueError('Reward ownership/specification differs from Store parity policy')
            elif source['policy_version'] == 'tournament_rewards_v2':
                from .tournament_reward_policy import allowed_pack_definitions
                expected_keys.add('untradeable')
                if (
                    e.get('untradeable') is not True
                    or e.get('definition') not in allowed_pack_definitions()
                ):
                    raise ValueError('Invalid tournament reward pack ownership/specification')
            elif source['policy_version'] == 'level_rewards_v1':
                from .level_rewards import allowed_pack_definitions as level_definitions
                expected_keys.add('untradeable')
                if e.get('untradeable') is not True or e.get('definition') not in level_definitions():
                    raise ValueError('Invalid level reward pack ownership/specification')
            elif source['policy_version'] == 'accomplishments_v1':
                from .accomplishments import allowed_pack_definitions as accomplishment_definitions
                expected_keys.add('untradeable')
                if e.get('untradeable') is not True or e.get('definition') not in accomplishment_definitions():
                    raise ValueError('Invalid accomplishment reward pack ownership/specification')
            elif source['policy_version'] == 'first_run_v1':
                from .first_run_account import allowed_pack_definitions as setup_definitions
                expected_keys.add('untradeable')
                if e.get('untradeable') is not True or e.get('definition') not in setup_definitions():
                    raise ValueError('Invalid welcome reward pack ownership/specification')
            if (set(e)!=expected_keys or owned is None or
                any(owned.get(k)!=v for k,v in e.items()) or e['catalog_id'] in catalogs):
                raise ValueError('Source pack entitlement missing/conflicting')
            keys.add(key);catalogs.add(e['catalog_id']);owners.add(source['account_id'])
        if len(owners)>1:raise ValueError('Foreign pack reward account')
        from .native_free_packs import validate_grants
        vouchers=validate_grants(value)
        restricted = {
            r['entitlement']['catalog_id'] for r in sources
            if r['policy_version'] in ('reward_store_parity_v1', 'tournament_rewards_v2', 'level_rewards_v1', 'accomplishments_v1', 'first_run_v1')
        }
        restricted.update(v['entitlement']['catalog_id'] for v in vouchers if v['entitlement'].get('untradeable') is True)
        for r in value['entitlements']+value['consumed']+([value['prepared']] if value.get('prepared') else []):
            if (r.get('untradeable') is True)!=(r['catalog_id'] in restricted):
                raise ValueError('Untradeable entitlement lacks its prospective reward source')
        if catalogs & {v['entitlement']['catalog_id'] for v in vouchers}:raise ValueError('Duplicate pack source ownership')
        return value
    def save(self,value):
        from .native_paid_pack_presentation import validate_pack_state
        validate_pack_state(self,value)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix=self.path.name+'.',dir=self.path.parent);temporary=Path(name)
        try:
            with os.fdopen(fd,'w') as file:
                file.write(json.dumps(value,indent=2,sort_keys=True)+'\n');file.flush();os.fsync(file.fileno())
            PackStore(temporary).load(value['persona_id']);temporary.replace(self.path)
            fd=os.open(self.path.parent,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
        finally:
            if temporary.exists():temporary.unlink()
    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.with_name(self.path.name+'.lock').open('a') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)
    def grant(self,definition,persona=1):
        if definition not in DEFINITIONS:raise ValueError('Unknown revival definition')
        with self.transaction():
            value=self.load(persona);key=value['next_catalog_id']
            if key>private_limit(value):raise ValueError('Local catalog identity exhausted')
            record={'catalog_id':key,'definition':definition,'provenance':'revival_policy'}
            value['entitlements'].append(record);value['next_catalog_id']=key+1;self.save(value)
            return record

    def _grant_from_source(self,definition,source,persona=1):
        """Caller holds the pack lock and validates the committed source owner.

        Single PackStore atomic replacement records source and unopened ownership
        together. This is backend test infrastructure, not a new wire contract.
        Never map a policy label to a substitute definition here.
        """
        before=self.load(persona)
        value,receipt=self.source_grant_image(before,definition,source)
        if value!=before:self.save(value)
        return receipt

    @staticmethod
    def source_grant_image(value,definition,source):
        """Pure existing entitlement transition for a caller-owned journal image."""
        import copy
        if definition not in DEFINITIONS:raise ValueError('Unknown revival definition')
        value=copy.deepcopy(value)
        if value.get('prepared'):raise ValueError('Recover existing opening before reward entitlement')
        records=value.get('source_grants',[])
        prior=next((r for r in records if r['reward_id']==source['reward_id']),None)
        if prior:
            if {k:v for k,v in prior.items() if k!='entitlement'}!=source or prior['entitlement']['definition']!=definition:
                raise ValueError('Pack reward retry conflicts with source/definition')
            return value,prior
        key=value['next_catalog_id']
        if key>private_limit(value):raise ValueError('Local catalog identity exhausted')
        entitlement={'catalog_id':key,'definition':definition,'provenance':'revival_policy'}
        if source.get('policy_version')=='reward_store_parity_v1':
            from .reward_store_parity import policy
            if definition not in {r['definition'] for r in policy()['bindings'].values()}:
                raise ValueError('Reward requires exact pinned Store definition')
            entitlement['untradeable']=True
        elif source.get('policy_version') == 'tournament_rewards_v2':
            from .tournament_reward_policy import allowed_pack_definitions
            if definition not in allowed_pack_definitions():
                raise ValueError('Tournament reward requires a pinned prize definition')
            entitlement['untradeable'] = True
        elif source.get('policy_version') == 'level_rewards_v1':
            from .level_rewards import allowed_pack_definitions as level_definitions
            if definition not in level_definitions():
                raise ValueError('Level reward requires a pinned milestone definition')
            entitlement['untradeable'] = True
        elif source.get('policy_version') == 'accomplishments_v1':
            from .accomplishments import allowed_pack_definitions as accomplishment_definitions
            if definition not in accomplishment_definitions():
                raise ValueError('Accomplishment reward requires a pinned policy definition')
            entitlement['untradeable'] = True
        elif source.get('policy_version') == 'first_run_v1':
            from .first_run_account import allowed_pack_definitions as setup_definitions
            if source.get('source_kind') != 'setup' or definition not in setup_definitions():
                raise ValueError('Welcome reward requires its pinned setup definition')
            entitlement['untradeable'] = True
        receipt={**source,'entitlement':entitlement}
        value['entitlements'].append(entitlement);value['next_catalog_id']=key+1
        value.setdefault('source_grants',[]).append(receipt)
        return value,receipt

    def new_draw_version(self, value):
        from .first_run_account import account_id
        from .native_pack_sessions import PRIVATE_VERSION
        if value.get('identity_version') != PRIVATE_VERSION:
            return None
        return 2 if account_id(self.path.parent) is not None else None

    def selection_key(self, catalog_id, draw_version=None):
        """Versioned draws: account entropy changes new pulls, never old receipts."""
        if draw_version is None:
            return catalog_id
        if type(draw_version) is not int or draw_version != 2:
            raise ValueError('Unknown pack draw version')
        from .first_run_account import account_id
        owner = account_id(self.path.parent)
        if owner is None:
            raise ValueError('Account-scoped draw requires its durable owner')
        from .native_pack_sessions import PRIVATE_MAX
        digest = hashlib.sha256(f'account_pack_draw_v2:{owner}'.encode()).digest()
        offset = int.from_bytes(digest[:8], 'big')
        # Keep consecutive allocations consecutive for the admitted rotation
        # policies, while every new club starts at an independent random phase.
        return 30001 + (catalog_id - 30001 + offset) % (PRIVATE_MAX - 30000)

    def preview(self,key,football,opening_identity=None):
        """No mutation during held probes. Commit regenerates under locks."""
        value=self.load()
        receipt=next((r for r in value['consumed'] if r['catalog_id']==key),None)
        if receipt:return receipt
        if value.get('prepared') and value['prepared']['catalog_id']==key:return value['prepared']
        entitlement=next((r for r in value['entitlements'] if r['catalog_id']==key),None)
        if entitlement is None:raise ValueError('Unknown local entitlement')
        return self.preview_entitlement(entitlement,football,opening_identity,value=value)

    def preview_entitlement(self,entitlement,football,opening_identity=None,*,value=None):
        """Pure opening preview of one entitlement, committed or prospective."""
        if value is None:
            value=self.load()
        key=entitlement['catalog_id']
        from .local_football import owned_instance_ids,OwnedPlayerItem,OwnedConsumableItem
        current=football.load(1);first=current.next_instance_id or max(owned_instance_ids(current),default=0)+1
        draw_version = self.new_draw_version(value)
        selection_key = self.selection_key(key, draw_version)
        pulls=select_pulls(entitlement['definition'],selection_key,private_identity_version=value.get('identity_version'))
        resources=tuple(c.resource_id for c in pulls)
        rule=DEFINITIONS[entitlement['definition']]
        if rule.get('selection')=='typed_tier_quota_v1' or rule.get('item_family') in ('mixed_bronze','mixed_silver','mixed_gold'):
            items=allocated_items(pulls,first,key,rule)
        else:
            items=(tuple(OwnedConsumableItem(first+n,rid) for n,rid in enumerate(resources)) if rule.get('item_family')=='consumable'
                   else tuple(OwnedPlayerItem(first+n,rid,rule['new_player_fitness'],player_formation(key,rid),
                       special_version_id=pulls[n].special_version_id) for n,rid in enumerate(resources)))
        receipt = {**entitlement, 'items': [asdict(item) for item in items]}
        if draw_version is not None:
            receipt['draw_version'] = draw_version
        if opening_identity is not None:
            receipt['opening_identity'] = opening_identity
        return receipt

    def _finish(self,value,receipt):
        value['entitlements']=[e for e in value['entitlements'] if e['catalog_id']!=receipt['catalog_id']]
        value['consumed'].append(receipt);value.pop('prepared',None);self.save(value)

    def _recover(self,value,football):
        if value.get('prepared'):
            receipt=value['prepared']
            football.mutate_inventory(1,grants=receipt_items(receipt),untradeable_grants=receipt.get('untradeable',False))
            self._finish(value,receipt)

    def recover(self,football):
        with self.transaction():self._recover(self.load(),football)

    def open(self,key,football,opening_identity=None):
        with self.transaction():
            value=self.load();self._recover(value,football);value=self.load()
            receipt=next((r for r in value['consumed'] if r['catalog_id']==key),None)
            if receipt:return receipt
            entitlement=next((r for r in value['entitlements'] if r['catalog_id']==key),None)
            if entitlement is None:raise ValueError('Unknown local entitlement')
            draw_version = self.new_draw_version(value)
            selection_key = self.selection_key(key, draw_version)
            pulls=select_pulls(entitlement['definition'],selection_key,private_identity_version=value.get('identity_version'))
            resources=tuple(c.resource_id for c in pulls)
            def prepare(items):
                receipt = {**entitlement, 'items': [asdict(item) for item in items]}
                if draw_version is not None:
                    receipt['draw_version'] = draw_version
                if opening_identity is not None:
                    receipt['opening_identity'] = opening_identity
                value['prepared'] = receipt
                self.save(value)
            rule=DEFINITIONS[entitlement['definition']]
            if entitlement.get('untradeable') is True:
                football.grant_mixed_items(1,lambda first:allocated_items(pulls,first,key,rule),prepare=prepare,untradeable=True)
            elif rule.get('selection')=='typed_tier_quota_v1' or rule.get('item_family') in ('mixed_bronze','mixed_silver','mixed_gold'):
                football.grant_mixed_items(1,lambda first:allocated_items(pulls,first,key,rule),prepare=prepare)
            elif rule.get('item_family')=='consumable':
                football.grant_consumables(1,resources,pile='unassigned',prepare=prepare)
            else:
                football.grant_players(1,resources,fitness=rule['new_player_fitness'],formation_ids=tuple(player_formation(key,rid) for rid in resources),special_version_ids=tuple(c.special_version_id for c in pulls),prepare=prepare)
            receipt=value['prepared'];self._finish(value,receipt)
            return receipt

def private_limit(value):
    from .native_pack_sessions import PRIVATE_VERSION,PRIVATE_MAX
    return PRIVATE_MAX if value.get('identity_version')==PRIVATE_VERSION else 65535

def catalog_response(store,value=None):
    value=store.load() if value is None else value
    rows=[]
    # Stock UnassignedItems opens packs[1]. Make an explicitly isolated test
    # entitlement reachable without consuming any existing development packs.
    # Ordering is local test policy, not a recovered EA catalog convention.
    entitlements=sorted(value['entitlements'],key=lambda e:DEFINITIONS[e['definition']].get('unopened_priority',-20 if DEFINITIONS[e['definition']]['selection']=='reconstructed_special_test' else 0))
    for entitlement in entitlements:
        definition=DEFINITIONS[entitlement['definition']]
        content=content_info(entitlement['definition'])
        if definition.get('item_family')=='consumable':
            from .local_consumables import inventory_reference as reference
            refs=[reference(rid) for rid in select_cards(entitlement['definition'],entitlement['catalog_id'],private_identity_version=value.get('identity_version'))]
            content={'itemQuantity':len(refs),'bronzeQuantity':sum(r['rating']<65 for r in refs),
                     'silverQuantity':sum(65<=r['rating']<75 for r in refs),'goldQuantity':sum(r['rating']>=75 for r in refs),
                     'rareQuantity':sum(r['weightrare']>0 for r in refs)}
        rows.append({'id':entitlement['catalog_id'],'displayGroup':{'value':'mypacks','priority':0},
            'categoryList':[{'categoryId':501,'orderInCategory':0}],
            'packType':'gold','unopened':True,'visible':1,'quantity':1,'state':'active',
            'packContentInfo':content,
            'description':definition['name']})
        if definition.get('item_family') in ('mixed_bronze','mixed_silver','mixed_gold'):
            rows[-1].update(packType=definition['quality'],isPremium=definition['is_premium'])
        elif definition.get('selection') == 'reviewed_tier_special_v1':
            rows[-1].update(packType=definition['quality'], isPremium=True)
    return {'purchase':rows}

def content_info(definition):
    rule=DEFINITIONS[definition]
    if rule.get('selection') == 'reviewed_tier_special_v1':
        return {
            'itemQuantity': 1,
            rule['quality'] + 'Quantity': 1,
            'rareQuantity': 1,
        }
    if rule.get('selection')=='typed_tier_quota_v1':
        return {'itemQuantity':rule['item_count'],**{t+'Quantity':n for t,n in rule['tier_counts'].items()},'rareQuantity':rule['minimum_rare']}
    if rule.get('item_family') in ('mixed_bronze','mixed_silver','mixed_gold'):
        return {'itemQuantity':rule['item_count'],rule['quality']+'Quantity':rule['minimum_'+rule['quality']],'rareQuantity':rule['minimum_rare']}
    if rule.get('item_family')!='consumable':
        if rule['quality']=='mixed':
            return {'itemQuantity':rule['item_count'],'rareQuantity':rule['minimum_rare']}
        return {'itemQuantity':rule['item_count'],'goldQuantity':rule['item_count'],'rareQuantity':rule['minimum_rare']}
    from .local_consumables import inventory_reference as reference
    refs=[reference(rid) for rid in select_cards(definition,30001)]
    return {'itemQuantity':len(refs),'bronzeQuantity':sum(r['rating']<65 for r in refs),
            'silverQuantity':sum(65<=r['rating']<75 for r in refs),'goldQuantity':sum(r['rating']>=75 for r in refs),
            'rareQuantity':sum(r['weightrare']>0 for r in refs)}

def pack_descriptions(store):
    """Recovered022f486c six-token resname -> numeric catalog ID, NAME/DESC/SHORT.

    Exact common labels/count text are recovered from supplied eng_us.db.
    No historical EA SKU or missing pack image identity is assigned.
    """
    from xml.etree import ElementTree as ET
    root=ET.Element('xliff')
    from . import native_pack_sessions as sessions
    from .first_run_account import pending_session
    if sessions.selected(store.path.parent):references=sessions.descriptions()
    elif pending_session(store.path.parent) is not None:
        references = sessions.pending_descriptions(store.path.parent)
    else:
        from .native_paid_pack_presentation import aliases
        owned=store.load()
        mapping=aliases(store,value=owned) if owned['entitlements'] else {}
        references=[(mapping.get(e['catalog_id'],e['catalog_id']),e['definition']) for e in owned['entitlements']]
        from .native_source_pack_presentation import descriptions as source_descriptions
        references.extend(source_descriptions(store,value=owned))
        from .reward_release import descriptions as reward_descriptions
        references.extend(reward_descriptions(store,value=owned))
        from .native_paid_caption_reservations import descriptions as paid_caption_descriptions
        references.extend(paid_caption_descriptions(store,value=owned))
        from .native_free_packs import descriptions as voucher_descriptions
        references.extend(voucher_descriptions(store,value=owned))
        products=store.path.with_name('products.json')
        if products.exists():
            from .local_store import active_offers
            references.extend((p['product_id'],p['definition']) for p in active_offers(products))
    seen={};caption_texts={}
    exact_card_sheet = False
    for catalog_id,definition in references:
        # The original descriptor map has one entry per numeric ID. Refuse a
        # conflicting paid/unopened alias instead of relabeling either pack.
        if catalog_id in seen:
            if seen[catalog_id]!=definition:raise ValueError('Conflicting paid/unopened descriptor identity')
            continue
        seen[catalog_id]=definition
        rule=DEFINITIONS[definition]
        from .original_pack_captions import captions
        if definition not in caption_texts:
            texts = captions(definition)
            expected_name = rule['name']
            if rule.get('selection') == 'specific_supplied_consumable_v1':
                from .store_single_captions import captions as exact_card_captions
                expected_name = exact_card_captions(definition)['NAME']
                exact_card_sheet = True
            if texts is not None and texts['NAME'] != expected_name:
                raise ValueError('Original caption/definition name disagreement')
            caption_texts[definition] = texts
        texts=caption_texts[definition]
        if texts is None:continue
        # Supplied locale keys use LONG, but original wire parser022f5b1c
        # compares the four-byte literal DESC (024ab9f6), not LONG.446
        # physically consumed NAME/SHORT while leaving content empty.
        from .original_pack_captions import display_name
        from . import client_build
        single_line_short = client_build.single_line_store_captions()
        for kind,value in texts.items():
            unit=ET.SubElement(root,'trans-unit',resname=f"FUT_STORE_MOBILE_PACK_{catalog_id}_{kind}")
            if kind=='NAME':
                value=display_name(value)
            elif kind=='SHORT' and single_line_short and '\n' in value:
                # 3.0 tile header has one line (run 1580); v26 keeps stacked counts.
                value=client_build.single_line(value)
            ET.SubElement(unit,'source').text=value
    # The original single-card formation text contains a curly apostrophe.
    # Expat does not treat the legacy "utf8" declaration as UTF-8 for it.
    # Keep historical sheets byte-identical; use the standard codec name for
    # new exact-card sheets so the complete descriptor document parses.
    encoding = 'utf-8' if exact_card_sheet else 'utf8'
    return ET.tostring(root,encoding=encoding) if len(root) else b'<xliff/>'
