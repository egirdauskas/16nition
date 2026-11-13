"""Authenticated Mobile TOTS evidence + separate deterministic revival stats.

Neither master nor account contains invented historical stats. Owned items and
pack receipts retain stable version references; later authentic fields resolve
through the provider without reallocating items or rewriting receipts.
"""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
POLICY=Path(__file__).parent/'policy/tots-stats-synthesis.json'
EVIDENCE=ROOT/'reports/mobile-tots-revival/historical-evidence.json'


def synthesize(base_stats,base_ovr,target_ovr,position,policy=None):
    policy=policy or json.loads(POLICY.read_text())
    if policy['classification']!='revival_policy' or policy.get('per_player_tuning') is not False:
        raise ValueError('Invalid synthesis provenance')
    if (len(base_stats)!=6 or any(type(x) is not int or not 1<=x<=99 for x in base_stats)
        or type(base_ovr) is not int or not 1<=base_ovr<=99 or type(target_ovr) is not int
        or not base_ovr<=target_ovr<=99):raise ValueError('Unusable base profile/confirmed OVR')
    groups=[g for g in policy['position_groups'].values() if position in g['positions']]
    if len(groups)!=1:raise ValueError('Unsupported synthesis position')
    weights=groups[0]['weights'];den=(100-base_ovr)*policy['weight_denominator'];delta=target_ovr-base_ovr
    if len(weights)!=6 or any(type(w) is not int or w<=0 for w in weights):raise ValueError('Invalid positional weights')
    return tuple(min(99,s+((99-s)*delta*w+den//2)//den) for s,w in zip(base_stats,weights))


def resolve_stats(record, policy_path=POLICY):
    from .local_content_source import attributes_for,rating_for,position_for
    rid=record['base_resource_id'];position=record['position'];keys=('DIV HAN KIC REF SPD POS' if position=='GK' else 'PAC SHO PAS DRI DEF PHY').split()
    base=attributes_for(rid)
    if (position=='GK') != (position_for(rid)=='GK'):raise ValueError('Incompatible base attribute family')
    authentic=record.get('authentic_face_stats') or {}
    if set(authentic)-set(keys) or any(type(v) is not int or not 0<=v<=99 for v in authentic.values()):raise ValueError('Invalid authentic stats')
    if len(authentic)==6:
        final=tuple(authentic[k] for k in keys);synthetic=None
    else:
        synthetic=synthesize(base,rating_for(rid),record['mobile_ovr'],position,json.loads(policy_path.read_text()))
        final=tuple(authentic.get(k,synthetic[i]) for i,k in enumerate(keys))
    policy=json.loads(policy_path.read_text())
    return {'special_version_id':record['special_version_id'],'historical_record_id':record['historical_record_id'],
        'confirmed_mobile_ovr':record['mobile_ovr'],'confirmed_position':position,'base_resource_id':rid,
        'base_ovr':rating_for(rid),'original_base_six_stats':dict(zip(keys,base)),
        'synthesized_six_stats':dict(zip(keys,synthetic)) if synthetic is not None else None,
        'effective_six_stats':dict(zip(keys,final)),
        'stats_provenance':'revival_policy_synthesized' if synthetic is not None else 'mobile_authentic_recovered',
        'synthesis_policy':policy['version'] if synthetic is not None else None,
        'synthesis_policy_sha256':hashlib.sha256(policy_path.read_bytes()).hexdigest() if synthetic is not None else None,
        'source_announcement_ids':record['source_announcement_ids'],
        'field_authenticity':{'ovr':'authentic','position':'authentic','base_resource_id':'preserved_mobile_content',
                             **{k:'authentic' if k in authentic else 'revival_policy_synthesized' for k in keys}},
        'authentic_field_sources':record['field_provenance'],
        'stats_source_classes':record.get('stats_source_classes',{}),
        'secondary_conflicts_preserved':record.get('secondary_conflicts',[])}


def reviewed_versions(mapping,config):
    """Feed the existing typed provider; fail closed on evidence/conflicts."""
    from .card_pool import card_index
    from .reconstructed_specials import SpecialVersion
    if not mapping.get('runtime_proven') or mapping['rareflag']!=11 or mapping['enum']!='TOTS_CARD':raise ValueError('TOTS mapping not proven')
    raw=EVIDENCE.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=config['historical_evidence_sha256']:raise ValueError('TOTS evidence changed; rebuild review')
    evidence=json.loads(raw);result={};excluded={};overlay=[]
    for r in evidence['records']:
        key=r['special_version_id'];reason=None
        card=card_index().get(r.get('base_resource_id'))
        if r.get('conflicts'):reason='unresolved_authentic_field_conflict'
        elif r.get('classification')!='ea_first_party_confirmed' or not r['source_announcement_ids']:reason='not_first_party_confirmed_mobile'
        elif r.get('player_identity',{}).get('status')=='confirmed_preserved_player' and card is None:reason='missing_preserved_base_card_or_stat_profile'
        elif r.get('match_status')!='matched' or card is None or not card.lookup_supported:reason='unresolved_or_unsupported_base'
        if reason:excluded[key]=reason;continue
        try:resolved=resolve_stats(r)
        except ValueError as e:excluded[key]=str(e);continue
        keys=('DIV HAN KIC REF SPD POS' if r['position']=='GK' else 'PAC SHO PAS DRI DEF PHY').split()
        eligibility={'policy_class':'revival_policy','base_quality':card.quality,'base_rare':card.rare,
                     'permanently_packable':True,'historical_release_window_ignored':True,'special_rating_does_not_rebucket':True,
                     'special_style_does_not_rebucket':True,'base_quality_conflict':False,'resolved_pack_families':[card.quality],
                     'basis':'preserved_base_snapshot','live_enabled':True}
        result[key]=SpecialVersion(key,card.resource_id,r['mobile_ovr'],r['position'],tuple(resolved['effective_six_stats'][k] for k in keys),11,
            {'classification':'mobile_historical_reconstruction','field_sources':r['field_provenance'],'presentation_mapping':mapping,
             'runtime_review_status':'proven','stats_provenance':resolved['stats_provenance'],'revival_stats_overlay':resolved,
             'historical_record_id':r['historical_record_id'],'source_announcement_ids':r['source_announcement_ids']},eligibility,'tots')
        overlay.append(resolved)
    return result,excluded,overlay
