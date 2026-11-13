"""Non-player market items (policy v1): facts, wire encoding, ownership changes.

A listing's `item` is a player unless it carries `kind`: ball/badge/kit/stadium
(club items), manager, or consumable (training/healing/position/formation).
Search categories follow the stock client (1406-1413): ball, stadium,
clubInfo (kits and badges) and staff (cat=manager; coach/physio stay empty).
"""

from dataclasses import replace

from . import market_economy as economy

CLUB_KINDS = ('ball', 'badge', 'kit', 'stadium')
CATEGORY_KINDS = {'ball': ('ball',), 'stadium': ('stadium',), 'clubInfo': ('badge', 'kit'),
                  'staff': ('manager',)}


def listing_facts(listing):
    item = listing['item']
    kind = item.get('kind')
    if kind is None:
        return economy.facts(item['resource_id'], item.get('special_version_id'))
    return economy.item_facts(kind, item['resource_id'])


def category_of(kind):
    for category, kinds in CATEGORY_KINDS.items():
        if kind in kinds:
            return category
    return None


def owned_entry(football, instance_id):
    """(kind, owned object) for any owned card of the account, or (None, None)."""
    from .local_football import OwnedClubItem
    for item in football.owned_items:
        if item.instance_id == instance_id:
            return 'player', item
    for item in football.owned_consumables:
        if item.instance_id == instance_id:
            return 'consumable', item
    for item in football.owned_club_items:
        if item.instance_id == instance_id and type(item) is OwnedClubItem:
            return item.item_type, item
    for item in getattr(football, 'owned_managers', ()):
        if item.instance_id == instance_id:
            return 'manager', item
    return None, None


def tradeable(kind, owned):
    """Facts of a sellable owned non-player item; ValueError when not tradeable."""
    if kind in CLUB_KINDS:
        return economy.item_facts(kind, owned.resource_id)
    if kind in ('consumable', 'manager'):
        return economy.item_facts(kind, owned.resource_id)
    raise ValueError('Item kind is not tradeable')


def snapshot(kind, owned):
    """The listing `item` dict for an owned non-player card."""
    value = {'id': owned.instance_id, 'kind': kind if kind in CLUB_KINDS + ('manager',) else 'consumable',
             'resource_id': owned.resource_id}
    if kind == 'manager' and owned.formation_id is not None:
        value['formation_id'] = owned.formation_id
    return value


def owned_object(item, instance_id):
    """The owned dataclass a listing's item becomes (bought) or showed (sold)."""
    from .local_football import OwnedClubItem, OwnedConsumableItem, OwnedManagerItem
    kind = item['kind']
    if kind in CLUB_KINDS:
        return OwnedClubItem(instance_id, item['resource_id'], kind)
    if kind == 'manager':
        return OwnedManagerItem(instance_id, item['resource_id'], item.get('formation_id'))
    return OwnedConsumableItem(instance_id, item['resource_id'])


def encode(item, instance_id, account):
    """Native itemData for an item listing (same encoders as the owned piles)."""
    from .football_protocol import encode_consumable, encode_manager, encode_owned_club_item
    owned = owned_object(item, instance_id)
    if item['kind'] in CLUB_KINDS:
        return encode_owned_club_item(owned, account)
    if item['kind'] == 'manager':
        return encode_manager(owned)
    return encode_consumable(owned, account)


def grant(football, item, instance_id):
    """Football state with a bought item owned in Unassigned (purchased pile)."""
    from .local_football import ItemLocation
    owned = owned_object(item, instance_id)
    location = football.inventory_locations + (ItemLocation(instance_id, 'unassigned'),)
    if item['kind'] in CLUB_KINDS:
        return replace(football, owned_club_items=football.owned_club_items + (owned,),
                       inventory_locations=location, next_instance_id=instance_id + 1)
    if item['kind'] == 'manager':
        return replace(football, owned_managers=football.owned_managers + (owned,),
                       inventory_locations=location, next_instance_id=instance_id + 1)
    raise ValueError('Consumables are not bought on the market')


def retire(football, kind, instance_id):
    """Football state without a sold item (ownership retired once)."""
    if kind == 'player':
        field = 'owned_items'
    elif kind == 'consumable':
        field = 'owned_consumables'
    elif kind == 'manager':
        field = 'owned_managers'
    else:
        field = 'owned_club_items'
    return replace(
        football,
        **{field: tuple(i for i in getattr(football, field) if i.instance_id != instance_id)},
        inventory_locations=tuple(l for l in football.inventory_locations if l.instance_id != instance_id),
        retired_instance_ids=tuple(sorted(set(football.retired_instance_ids) | {instance_id})),
    )


def supply_pool(category):
    """Sorted (kind, resource_id) pool for a bot item category."""
    from .local_club_items import references
    from .local_content_source import managers
    if category == 'staff':
        return [('manager', rid) for rid in sorted(managers())]
    kinds = CATEGORY_KINDS[category]
    return sorted((row['item_type'], rid) for rid, row in references().items() if row['item_type'] in kinds)
