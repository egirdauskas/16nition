"""Configured revival_policy SKUs and single-use offers; no entitlement ownership."""
import json
from pathlib import Path
from .local_packs import DEFINITIONS,content_info
from .local_profile import validate_credits
PRODUCT_OVERLAY=None

def configure_product_overlay(path=None):
    """Service-scoped policy catalog; never copy products into account state."""
    global PRODUCT_OVERLAY
    candidate=Path(path).resolve() if path is not None else None
    if candidate is not None and not candidate.is_file():raise ValueError('Missing Store product overlay')
    PRODUCT_OVERLAY=candidate

def products(path):
    path=Path(path)
    if not path.exists():return []
    value=json.loads(path.read_text())
    dual=value.get('version') in (
        'local_store_catalog_v2', 'local_store_catalog_v3', 'local_store_catalog_v4',
        'local_store_catalog_v5', 'local_store_catalog_v6', 'local_store_catalog_v7',
    )
    keys={'persona_id','products','version'} if dual else {'persona_id','products'}
    if set(value)!=keys or type(value['persona_id']) is not int or value['persona_id']!=1 or type(value['products']) is not list:
        raise ValueError('Invalid local Store catalog')
    if dual:
        from .store_fp_policy import validate_catalog
        validate_catalog(value)
        if PRODUCT_OVERLAY is not None:raise ValueError('Versioned FP catalog excludes legacy product overlays')
    if PRODUCT_OVERLAY is not None:
        if path.resolve()==PRODUCT_OVERLAY:raise ValueError('Store overlay cannot replace its account catalog')
        extra=json.loads(PRODUCT_OVERLAY.read_text())
        if (not {'persona_id','products'}<=set(extra) or set(extra)-{'persona_id','products','definition_overrides'} or
            type(extra['persona_id']) is not int or extra['persona_id']!=value['persona_id'] or type(extra['products']) is not list):
            raise ValueError('Invalid Store product overlay')
        overrides=extra.get('definition_overrides',{})
        if type(overrides) is not dict:raise ValueError('Invalid Store definition overrides')
        for source,target in overrides.items():
            if type(source) is not str or type(target) is not str or source not in DEFINITIONS or target not in DEFINITIONS:
                raise ValueError('Unknown Store definition override')
            old,new=DEFINITIONS[source],DEFINITIONS[target]
            if (old.get('item_family','player')!='player' or new.get('item_family','player')!='player' or
                old['quality']!=new['quality'] or old['quality']!='gold' or
                any(old[k]!=new[k] for k in ('name','item_count','minimum_rare'))):
                raise ValueError('Store override must preserve Gold product guarantees')
        for row in value['products']:
            if row.get('definition') in overrides:row['definition']=overrides[row['definition']]
        value['products'].extend(extra['products'])
    seen=set()
    for row in value['products']:
        price_keys=set(row)&{'coin_price','point_price'}
        if ((not price_keys or (not dual and len(price_keys)!=1)) or set(row)-{'purchase_limit','repeatable','featured'}!={'product_id','definition','provenance'}|price_keys or row['provenance']!='revival_policy'
            or row['definition'] not in DEFINITIONS or type(row['product_id']) is not int
            or not 40001<=row['product_id']<=65535 or row['product_id'] in seen):raise ValueError('Invalid local Store offer')
        for price_key in price_keys:
            price=row[price_key]
            validate_credits(price)
            if price==0:raise ValueError('Paid Store offer needs a price')
        limit=row.get('purchase_limit',1)
        if type(limit) is not int or not 1<=limit<=99:raise ValueError('Invalid purchase limit')
        if type(row.get('repeatable',False)) is not bool:raise ValueError('Invalid repeatable policy')
        if type(row.get('featured',False)) is not bool:raise ValueError('Invalid featured policy')
        seen.add(row['product_id'])
    # STORE-006: selected release-demo offers are appended from their own
    # versioned policy; products.json and its pinned releases stay unchanged.
    from .store_demo_offers import extra_products
    extra=extra_products(path)
    if any(row['product_id'] in seen for row in extra):raise ValueError('Demo offer collides with the Store catalog')
    return value['products']+extra

def active_offers(path,journal=None):
    """Stable SKU -> current single-use wire offer; pure, no catalog lease writes.

    Revival policy: the client echoes our existing catalog id field. Old ids
    remain immutable receipt keys. No timestamp, refresh heuristic or nonce.
    """
    if journal is None:
        p=Path(path).with_name('purchases.json')
        journal=json.loads(p.read_text()) if p.exists() else {'receipts':[]}
    from . import native_pack_sessions as sessions
    # STORE-006: retired SKUs stay in the pinned catalog (caption bindings) but are not offered.
    from .store_demo_offers import retired_products
    retired=retired_products(path)
    if sessions.selected(Path(path).parent):
        return [o for o in sessions.offers(path,journal) if o.get('sku_id',o['product_id']) not in retired]
    result=[]
    history=journal['receipts']+([journal['prepared']] if 'prepared' in journal else [])
    used={r['product_id']:r for r in history}
    for row in products(path):
        item=dict(row)
        if row.get('repeatable'):
            sku=row['product_id']
            prior=[r for r in history if r.get('sku_id')==sku]
            item['sku_id']=sku
            item['product_id']=prior[-1]['next_product_id'] if prior else sku
            if item['product_id'] in used:
                raise ValueError('Repeatable SKU collides with retired offer')
        result.append(item)
    ids=[r['product_id'] for r in result]
    if len(set(ids))!=len(ids):raise ValueError('Catalog offer identity collision')
    return [r for r in result if r.get('sku_id',r['product_id']) not in retired]

def next_offer_id(path,journal,sku=None):
    """Never reuse an issued offer id, including retired/removed SKU reservations."""
    from . import native_pack_sessions as sessions
    if sessions.selected(Path(path).parent):
        product=next(p for p in active_offers(path,journal) if p['sku_id']==sku)
        return product['product_id']+1
    history=journal['receipts']+([journal['prepared']] if 'prepared' in journal else [])
    ids=[p['product_id'] for p in products(path)]
    ids += [r['product_id'] for r in history]+[r['next_product_id'] for r in history if 'next_product_id' in r]
    key=max(ids,default=40000)+1
    from .native_paid_caption_reservations import successor
    key=successor(path,journal,sku,key)
    if key>65535:raise ValueError('Store offer allocator exhausted')
    return key

def catalog_rows(path):
    from .original_pack_captions import display_name
    rows=[]
    journal=Path(path).with_name('purchases.json')
    receipts=json.loads(journal.read_text())['receipts'] if journal.exists() else []
    from . import native_pack_sessions as sessions
    if sessions.selected(Path(path).parent):
        epoch=sessions.current()
        receipts=[r for r in receipts if epoch and r.get('session_id')==epoch['sid']]
    bought=[r['product_id'] for r in receipts]
    for order,product in enumerate(active_offers(path)):
        remaining=product.get('purchase_limit',1)-bought.count(product['product_id'])
        if remaining<=0:continue
        rule=DEFINITIONS[product['definition']]
        currencies=[{'name':name,'funds':product[key],'finalFunds':product[key]}
            for name,key in [('coins','coin_price'),('points','point_price')] if key in product]
        consumable=rule.get('item_family')=='consumable'
        rows.append({'id':product['product_id'],'displayGroup':{'value':'consumables' if consumable else 'featured','priority':0},
            'categoryList':[] if consumable else [{'categoryId':401,'orderInCategory':order}],
            'packType':'gold','unopened':False,'visible':1,'quantity':remaining,'purchaseLimit':remaining,'state':'active',
            'currencies':currencies,
            'packContentInfo':content_info(product['definition']),
            'description':display_name(rule['name'])})
        if rule.get('item_family') in ('mixed_bronze','mixed_silver','mixed_gold'):
            rows[-1].update(packType=rule['quality'],isPremium=rule['is_premium'])
        #0102b2a4 key79/customAttribute == literal"Featured" sets source+8c;
        #0104db94 copies it to native pack+34;021e9088 requires this byte.
        if product.get('featured',product.get('repeatable',False)):
            rows[-1]['customAttribute']='Featured'
        from .store_demo_offers import row_fields
        rows[-1].update(row_fields(product.get('sku_id',product['product_id']),path))
        if rule.get('selection')=='consumables_tier_quota_v1':
            from .specialist_consumable_packs import category_ids
            categories=category_ids(product['definition'])
            rows[-1]['categoryList']=[{'categoryId':i,'orderInCategory':order} for i in categories]
            rows[-1]['displayGroup']['value']='consumables' if categories else 'featured'
        if rule.get('selection') == 'specific_supplied_consumable_v1':
            from .store_single_consumables import category_ids
            rows[-1].update(packType=rule['quality'], isPremium=bool(rule['minimum_rare']))
            rows[-1]['categoryList'] = [
                {'categoryId': i, 'orderInCategory': order}
                for i in category_ids(product['definition'])
            ]
        if rule.get('item_family') in ('non_player','club_item') or product['definition']=='revival_consumables_only_v4':
            rows[-1]['categoryList']=[]
            rows[-1]['displayGroup']['value']='featured'
    # Isolated row probe only: "_first" moves a demo row to the front of the list.
    first = [r for r in rows if r.pop('_first', False)]
    if not first:
        return rows
    rows = first + [r for r in rows if r not in first]
    # Featured follows row order (1520); the Players tab follows orderInCategory (run 1526
    # showed BRAZIL PACK last there), so renumber category 401 to the final row order.
    position = 0
    for row in rows:
        for entry in row.get('categoryList', []):
            if entry.get('categoryId') == 401:
                entry['orderInCategory'] = position
                position += 1
    return rows
