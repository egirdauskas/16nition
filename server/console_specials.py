"""Console TOTS/TOTW specials admitted under revival_policy console_tots_policy_v1.

User authorization, 7 November 2026: leagues without an authoritative Mobile source get the
console TOTS squads (Bundesliga thumbnail cards and the Liga NOS thumbnail roster with console
stats; Big 5 Mobile cards unchanged); then all console TOTW in-forms "in the same manner".
Stats come from fut.gg and archived Futhead card pages (a few from Mobile thumbnails or user
transcriptions); every record names its source. The datasets are SHA-pinned in the
reconstructed-specials policy and are not research masters.

Presentation reuses the runtime-proven TOTS (rareflag 11) and TOTW (rareflag 3) mappings.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GK_KEYS = ('DIV', 'HAN', 'KIC', 'REF', 'SPD', 'POS')
OUT_KEYS = ('PAC', 'SHO', 'PAS', 'DRI', 'DEF', 'PHY')


def _dataset(entry):
    raw = (ROOT / entry['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ValueError('Console specials dataset changed; review policy: ' + entry['path'])
    value = json.loads(raw)
    if value.get('classification') != 'console_tots_policy_v1':
        raise ValueError('Unexpected console dataset classification')
    return value['cards']


def _record_id(family, card):
    if family == 'console_totw':
        return 'console_totw:w%d:%d:%d' % (card['weeks'][0], card['base_resource_id'], card['ovr'])
    return 'console_tots:%s:%d:%d' % (card['squad'], card['base_resource_id'], card['ovr'])


def reviewed_versions(mappings, config):
    """({record_id: SpecialVersion}, {record_id: reason}) for the SHA-pinned console datasets."""
    from .card_pool import card_index
    from .reconstructed_specials import SpecialVersion
    if config.get('classification') != 'revival_policy' or config.get('version') != 'console_tots_policy_v1':
        raise ValueError('Console specials require the authorized revival policy')
    index = card_index()
    result, excluded = {}, {}
    for entry in config['datasets']:
        family = entry['family']
        mapping = mappings[entry['presentation_mapping']]
        if not mapping.get('runtime_proven', mapping.get('enum') == 'TOTW_CARD') or not mapping.get('runtime_evidence'):
            raise ValueError('Console family needs a runtime-proven presentation')
        for card in _dataset(entry):
            key = _record_id(family, card)
            if key in result or key in excluded:
                raise ValueError('Duplicate console record ' + key)
            base = index.get(card['base_resource_id'])
            keys = GK_KEYS if card['position'] == 'GK' else OUT_KEYS
            stats = card.get('stats') or {}
            reason = None
            if base is None or not base.lookup_supported:
                reason = 'unresolved_or_unsupported_base'
            elif set(stats) != set(keys) or any(type(stats[k]) is not int or not 1 <= stats[k] <= 99 for k in keys):
                reason = 'incomplete_face_stats'
            elif type(card['ovr']) is not int or not 40 <= card['ovr'] <= 99:
                reason = 'invalid_overall'
            if reason:
                excluded[key] = reason
                continue
            eligibility = {
                'policy_class': 'revival_policy', 'base_quality': base.quality, 'base_rare': base.rare,
                'permanently_packable': True, 'historical_release_window_ignored': True,
                'special_rating_does_not_rebucket': True, 'special_style_does_not_rebucket': True,
                'base_quality_conflict': False, 'resolved_pack_families': [base.quality],
                'basis': 'preserved_base_snapshot',
            }
            provenance = {
                'classification': 'console_tots_policy_v1', 'approval_classification': 'revival_policy',
                'dataset': entry['path'], 'dataset_sha256': entry['sha256'],
                'source_url': card.get('source_url'), 'selection': card.get('selection'),
                'futhead_card_id': card.get('futhead_card_id'), 'weeks': card.get('weeks'),
                'squad': card.get('squad'), 'family_exception': card.get('family_exception'),
                'presentation_mapping': mapping,
                'runtime_review_status': 'proven',
            }
            result[key] = SpecialVersion(key, base.resource_id, card['ovr'], card['position'],
                                         tuple(stats[k] for k in keys), mapping['rareflag'],
                                         provenance, eligibility, family)
    return result, excluded
