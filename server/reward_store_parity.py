"""Prospective reward quotes using immutable, admitted Store definitions.

This is revival policy, not a wire adapter or an activation switch. Old source
snapshots remain owned by their original policy. Composition and ownership are
separate: a reward reuses the Store definition and requires untradeable items.
"""
import copy
import hashlib
import json
from pathlib import Path

PATH = Path(__file__).parent / 'policy/reward-store-parity-v1.json'


def digest(value):
    return hashlib.sha256((json.dumps(value, indent=2, sort_keys=True) + '\n').encode()).hexdigest()


def policy():
    from .local_packs import DEFINITIONS
    value = json.loads(PATH.read_bytes())
    fields = {'version', 'classification', 'default_enabled', 'stock_delivery_enabled',
              'ownership', 'applies_to', 'existing_entitlements', 'store_catalog_sha256', 'bindings'}
    if (set(value) != fields or value['version'] != 'reward_store_parity_v1' or
            value['classification'] != 'revival_policy' or value['default_enabled'] is not False or
            value['stock_delivery_enabled'] is not False or value['ownership'] != 'untradeable' or
            value['applies_to'] != ['fixture', 'championship'] or
            value['existing_entitlements'] != 'preserve'):
        raise ValueError('Unsupported reward Store parity policy')
    # These labels also include the two non-reward player products. Keeping the
    # complete standard catalog pinned makes parity independently auditable.
    labels = {'Bronze', 'Premium Bronze', 'Silver', 'Premium Silver', 'Gold',
              'Premium Gold', 'Jumbo Premium Gold', 'Premium Gold Players', 'Mega',
              'Rare Players', 'Jumbo Rare Players', 'Ultimate'}
    if type(value['bindings']) is not dict or set(value['bindings']) != labels:
        raise ValueError('Complete standard Store bindings required')
    hashes = [value['store_catalog_sha256']]
    for row in value['bindings'].values():
        if (type(row) is not dict or set(row) != {'definition', 'definition_sha256'} or
                row['definition'] not in DEFINITIONS or
                row['definition_sha256'] != digest(DEFINITIONS[row['definition']])):
            raise ValueError('Reward definition differs from pinned Store specification')
        hashes.append(row['definition_sha256'])
    if any(type(h) is not str or len(h) != 64 or any(c not in '0123456789abcdef' for c in h) for h in hashes):
        raise ValueError('Invalid Store parity digest')
    return value


def current_store_bindings():
    """Audit current Store parity, never use a mutable catalog to replay a quote."""
    from .store_pool_amendment import catalog
    from .local_packs import DEFINITIONS
    value = policy()
    rows = catalog()
    if value['store_catalog_sha256'] != digest(rows):
        raise ValueError('Current Store catalog requires a new prospective reward policy')
    admitted = {r['definition'] for r in rows['products']}
    if any(r['definition'] not in admitted or digest(DEFINITIONS[r['definition']]) != r['definition_sha256']
           for r in value['bindings'].values()):
        raise ValueError('Reward definition is absent from admitted Store catalog')
    return copy.deepcopy(value['bindings'])


def snapshot(division,*,current=True):
    """All approved match outcomes and title quote; no invented lesser bonus."""
    from .revival_rewards import load_reward_policy
    if type(division) is not int or not 1 <= division <= 10:
        raise ValueError('Invalid reward division')
    value = policy()
    if current:current_store_bindings()
    table = load_reward_policy()['divisions'][str(division)]
    return {'version': value['version'], 'classification': 'backend_only',
            'policy_sha256': hashlib.sha256(PATH.read_bytes()).hexdigest(),
            'division': division, 'ownership': value['ownership'],
            'outcomes': {result: {'label': row['pack_label'], **copy.deepcopy(value['bindings'][row['pack_label']])}
                         for result, row in table['match'].items()},
            'championship': {'label': table['season']['CHAMPIONSHIP']['pack_label'],
                             **copy.deepcopy(value['bindings'][table['season']['CHAMPIONSHIP']['pack_label']])}}


def validate_snapshot(value):
    if type(value) is not dict or value != snapshot(value.get('division'),current=False):
        raise ValueError('Invalid pinned Store parity reward quote')
    return value
