"""Compact prospective pack references; full images live only in pending intents.

Legacy source snapshots remain readable/unchanged. This is a versioned input to
the existing coordinator, not a new journal or an alternative reward mechanism.
"""
import hashlib
import json
import uuid

VERSION = 'atomic_pack_reference_v2'
VERSION_WIDE='atomic_pack_reference_v3'


def compact(pack):
    return pack.get('version') in (VERSION,VERSION_WIDE)


def snapshot(raw, policy):
    value = json.loads(raw)
    if value.get('prepared') or value['persona_id'] != 1:
        raise ValueError('Quiescent owned pack snapshot required')
    return {'version': VERSION_WIDE if value.get('identity_version')=='private_pack_identity_v2' else VERSION, 'policy': policy,
            'packs_before_sha256': hashlib.sha256(raw).hexdigest(),
            'next_catalog_id': value['next_catalog_id']}


def validate(pack, committed):
    fields = {'version','policy','next_catalog_id'}
    if not committed: fields.add('packs_before_sha256')
    if set(pack)-{'grant','championship_start'} != fields:
        raise ValueError('Invalid compact atomic pack reference')
    limit=0x7ffffffffffffffe if pack.get('version')==VERSION_WIDE else 65535
    if type(pack['next_catalog_id']) is not int or not 30001 <= pack['next_catalog_id'] <= limit:
        raise ValueError('Invalid compact pack allocator')
    if not committed:
        h = pack['packs_before_sha256']
        if type(h) is not str or len(h) != 64 or any(c not in '0123456789abcdef' for c in h):
            raise ValueError('Invalid compact pack digest')


def baseline(pack, raw):
    if hashlib.sha256(raw).hexdigest() != pack['packs_before_sha256']:
        raise ValueError('Atomic pack projections changed before commit')
    value = json.loads(raw)
    if (value.get('prepared') or value['persona_id'] != 1
            or value['next_catalog_id'] != pack['next_catalog_id']):
        raise ValueError('Compact pack baseline identity/allocator mismatch')
    return value


def grant(state, source, definition, *, completion=None):
    """Reconstruct one deterministic receipt, never the whole pack history."""
    kind = 'season' if completion is not None else 'fixture'
    owner = completion if completion is not None else source
    policy = ('reward_store_parity_v1' if source['atomic_pack']['policy']['version'] == 'reward_store_parity_v1'
              else 'backend_pack_entitlement_test_v1')
    entitlement = {'catalog_id': source['atomic_pack']['next_catalog_id']+int(completion is not None),
                   'definition': definition, 'provenance': 'revival_policy'}
    if policy == 'reward_store_parity_v1': entitlement['untradeable'] = True
    return {'reward_id': str(uuid.uuid5(uuid.UUID(owner['id']), kind+'-pack')),
            'source_id': owner['id'], 'source_kind': kind, 'account_id': state['account_id'],
            'persona_id': state['account_identity']['persona_id'], 'cycle_id': source['cycle_id'],
            'policy_version': policy, 'certification': 'backend_only', 'entitlement': entitlement}
