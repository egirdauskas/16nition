"""Explicitly authorized approximate FIFA16 values, separate from wire contracts."""
import hashlib,json
from pathlib import Path
from .local_football import OwnedPlayerItem,OwnedConsumableItem,OwnedClubItem

PATH=Path(__file__).parent/'policy/quick-sell-fifa16-approx-v1.json'
VERSION='quick_sell_fifa16_approx_v1'
CLUB_PATH=Path(__file__).parent/'policy/club-item-quick-sell-console-v1.json'

def club_policy():
    raw=CLUB_PATH.read_bytes();value=json.loads(raw)
    if (value.get('version')!='club_item_quick_sell_console_v1' or value.get('classification')!='revival_policy' or
        value.get('club_items')!={'bronze':[3,13],'silver':[14,37],'gold':[31,60]} or value.get('ball_coins')!=15):
        raise ValueError('Unapproved club-item quick-sell policy')
    return value,hashlib.sha256(raw).hexdigest()

def policy():
    raw=PATH.read_bytes();v=json.loads(raw)
    if v.get('version')!=VERSION or v.get('classification')!='revival_policy' or v.get('rounding')!='half_up_per_item':
        raise ValueError('Unapproved quick-sell policy')
    return v,hashlib.sha256(raw).hexdigest()

def tier(rating):
    if type(rating) is not int or not 40<=rating<=99:raise ValueError('Unsupported valuation rating')
    return 'gold' if rating>=75 else 'silver' if rating>=65 else 'bronze'

def player_coins(rating, category, value=None):
    """Quick-sell coins of a player card: common, rare or special at this OVR."""
    if value is None:
        value = policy()[0]
    numerator, denominator = value['player_multipliers'][tier(rating)][category]
    return (2 * numerator * rating + denominator) // (2 * denominator)

def quote(item,*,untradeable=False):
    if type(untradeable) is not bool:raise ValueError('Explicit ownership restriction required')
    if untradeable:
        # Restriction is ownership metadata, never a change to historical prices.
        return {**quote(item),'untradeable':True,'coins':0}
    if type(item) is OwnedClubItem:
        from .local_club_items import reference,quality
        row=reference(item.item_type,item.resource_id);v,sha=club_policy()
        coins=v['ball_coins'] if item.item_type=='ball' else v['club_items'][quality(row)][row['rare']]
        return {'instance_id':item.instance_id,'resource_id':item.resource_id,'special_version_id':None,
                'kind':'club','item_type':item.item_type,'coins':coins,'policy_version':v['version'],'policy_sha256':sha}
    v,sha=policy();special=None
    if type(item) is OwnedPlayerItem:
        from .card_pool import card_index
        card=card_index().get(item.resource_id)
        if card is None or not card.lookup_supported:raise ValueError('Unsupported player valuation')
        if item.special_version_id is not None:
            from .reconstructed_specials import version
            special=version(item.special_version_id)
            if special.base_resource_id!=item.resource_id:raise ValueError('Special/base ownership mismatch')
            rating=special.rating;category='special'
        else:
            if card.variant_bits:raise ValueError('Unreviewed shipped variant valuation')
            rating=card.rating;category='rare' if card.rare else 'common'
        coins=player_coins(rating,category,v)
        kind='player'
    elif type(item) is OwnedConsumableItem:
        from .local_consumables import pack_references,CURRENT_POOL,INJURY_SUBTYPES
        row=pack_references(CURRENT_POOL).get(item.resource_id)
        if row is None:raise ValueError('Filtered/unsupported consumable valuation')
        subtype=row['cardsubtype'];quality=tier(row['rating']);rare=int(row['weightrare']>0)
        if 51<=subtype<=57 or 61<=subtype<=67:family='training'
        elif 71<=subtype<=86 or 121<=subtype<=136:family='formation'
        elif 91<=subtype<=110:family='position'
        elif subtype in INJURY_SUBTYPES:family='healing'
        elif subtype in v['misc_scope']:family=None
        else:raise ValueError('Unmapped consumable valuation family')
        coins=v['misc_token_value'] if family is None else v['consumables'][family][quality][rare]
        kind='consumable'
    else:raise ValueError('Unsupported quick-sell item type')
    if type(coins) is not int or not 0<=coins<=0x7fffffff:raise ValueError('Invalid discard value')
    return {'instance_id':item.instance_id,'resource_id':item.resource_id,
            'special_version_id':item.special_version_id if type(item) is OwnedPlayerItem else None,
            'kind':kind,'coins':coins,'policy_version':VERSION,'policy_sha256':sha}
