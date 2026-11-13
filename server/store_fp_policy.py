"""Explicit FIFA16-console price fallback, not recovered Mobile pack prices."""
import json
from pathlib import Path
from .classic_pack_store import projection, POLICY_V11, SUPPORTED_V11

PATH=Path(__file__).parent/'policy/store-fp-prices-fifa16-console-v1.json'
CATALOG_VERSION='local_store_catalog_v2'

def point_prices():
    value=json.loads(PATH.read_bytes())
    if (value['version']!='store_fp_prices_fifa16_console_v1' or
        value['classification']!='user_authorized_console_fallback' or value['default_enabled'] is not False or
        value['source']['platform']!='FIFA 16 console FUT' or
        value['source']['url']!='https://fifauteam.com/fifa-16-ultimate-team-packs/'):
        raise ValueError('Unsupported FP price provenance')
    prices=value['point_prices']
    if set(prices)!=set(SUPPORTED_V11):raise ValueError('Complete supported FP price book required')
    for name,price in prices.items():
        if name in ('Bronze','Premium Bronze'):
            if price is not None:raise ValueError('Historical regular Bronze packs have no FP price')
        elif type(price) is not int or price<=0:
            raise ValueError('Positive documented FP price required')
    return prices

def catalog():
    value=projection(POLICY_V11,backend_only=True);prices=point_prices()
    value['version']=CATALOG_VERSION
    labels=list(SUPPORTED_V11)
    for i,row in enumerate(value['products']):
        row['product_id']=48001+i
        if prices[labels[i]] is not None:row['point_price']=prices[labels[i]]
    return value

def validate_catalog(value):
    if value.get('version') == 'local_store_catalog_v7':
        from .store_single_consumables import catalog as single_catalog
        if value != single_catalog():
            raise ValueError('Individual consumables changed approved Store products or prices')
        return
    if value.get('version')=='local_store_catalog_v6':
        from .pack_family_split import catalog as split_catalog
        if value!=split_catalog():raise ValueError('Pack-family split catalog differs from approved policy')
        return
    if value.get('version')=='local_store_catalog_v5':
        from .standard_pack_specs import catalog as exact_catalog
        if value!=exact_catalog():
            from .store_pool_amendment import catalog as amended
            if value!=amended():raise ValueError('Exact pack specifications changed approved products/prices')
        return
    if value.get('version')=='local_store_catalog_v4':
        from .club_item_packs import catalog as club_catalog
        if value!=club_catalog():raise ValueError('Club-item catalog changes approved prices/products')
        return
    if value.get('version')=='local_store_catalog_v3':
        from .specialist_consumable_packs import catalog as specialist_catalog
        if value!=specialist_catalog():raise ValueError('Specialist catalog changes approved existing products')
        return
    if value!=catalog():raise ValueError('Versioned FP catalog must preserve approved prices, pools and local identities')
