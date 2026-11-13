"""Disabled prospective bindings: approved mixed packs gain supplied club cards.

No automatic catalog migration. Existing purchased entitlements, source reward
snapshots, specialist consumable packs and player-only packs retain definitions.
"""
import copy,json
from pathlib import Path
from .local_club_items import POOL
from .policy_memo import policy_memo

PATH=Path(__file__).parent/'policy/club-item-pack-bindings-v1.json'

@policy_memo
def bindings():
    from .pack_policy import load_definitions,crowd_filtered_consumable_bindings
    value=json.loads(PATH.read_text());definitions=load_definitions()
    expected={'version':'club_item_pack_bindings_v1','classification':'revival_policy',
        'default_enabled':False,'stock_delivery_enabled':False,'pool':POOL}
    if (set(value)!=set(expected)|{'bindings'} or
        any(type(value[k]) is not type(v) or value[k]!=v for k,v in expected.items())):
        raise ValueError('Invalid prospective club-item bindings')
    previous=crowd_filtered_consumable_bindings()
    if type(value['bindings']) is not dict or set(value['bindings'])!=set(previous):
        raise ValueError('Complete existing catalog required')
    result={}
    for label,row in value['bindings'].items():
        if (type(row) is not dict or set(row)!={'previous_definition','definition'} or
            row['previous_definition']!=previous[label]):raise ValueError('Historical binding changed')
        old,new=(definitions[row[k]] for k in ('previous_definition','definition'))
        if old.get('item_family','').startswith('mixed_'):
            if row['definition']==row['previous_definition'] or new!={**old,'club_item_pool':POOL}:
                raise ValueError('Only supplied club-card eligibility may change')
        elif row['definition']!=row['previous_definition'] or new!=old:
            raise ValueError('Player-only definition must remain unchanged')
        result[label]=row['definition']
    return result

def candidate_catalog(catalog):
    """Explicit lab proposal, never write an account or rewrite old receipts."""
    value=copy.deepcopy(catalog)
    if value.get('version') in ('local_store_catalog_v2','local_store_catalog_v3'):
        value['version']='local_store_catalog_v4'
    new=bindings()
    from .pack_policy import crowd_filtered_consumable_bindings
    old=crowd_filtered_consumable_bindings()
    replacements={old[label]:new[label] for label in old}
    for n,product in enumerate(value['products']):
        definition=product['definition']
        product['definition']=replacements.get(definition,definition)
        # A fresh local SKU namespace preserves issued offers and their retries.
        # These are local service identities, never asserted historical EA IDs.
        product['product_id']=61001+n
    return value

@policy_memo
def catalog():
    from .specialist_consumable_packs import catalog as previous
    return candidate_catalog(previous())
