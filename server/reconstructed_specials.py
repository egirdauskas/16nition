"""Reviewed historical versions; preserved identity, presentation and pool tier differ.

The SHA-pinned research master remains immutable. Family approvals and selection
policy live outside it; every admitted/excluded record has a deterministic reason.
"""
from dataclasses import dataclass
from functools import lru_cache
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
POLICY=Path(__file__).parent/'policy/reconstructed-specials.json'

@dataclass(frozen=True)
class SpecialVersion:
    record_id:str
    base_resource_id:int
    rating:int
    position:str
    attributes:tuple
    rareflag:int
    provenance:dict
    pack_eligibility:dict
    family:str='totw'


def review_record(record, family, mapping, conflicts=()):
    """Fail closed at the first unmet review prerequisite; no guessed fields."""
    if record['record_id'] in mapping.get('historical_record_exclusions',{}):
        return mapping['historical_record_exclusions'][record['record_id']]
    from .card_pool import card_index
    from .local_content_source import POSITION_WIRE
    supported={'TOTW_CARD':3,'PURPLE_CARD':4,'BLUE_CARD':5,'BLUERED_CARD':6,'GREEN_CARD':7,'ORANGE_CARD':8,'PINK_CARD':9,'TEAL_CARD':10,'TOTS_CARD':11,'HALLOWEEN':13,'HOLIDAY':14}
    families=mapping.get('historical_families',['totw'] if mapping.get('enum')=='TOTW_CARD' else [])
    if family not in families or supported.get(mapping.get('enum'))!=mapping.get('rareflag'):
        return 'unreviewed_family_or_presentation'
    if mapping.get('historical_events') and record['event_id'] not in mapping['historical_events']:
        return 'unreviewed_event_for_presentation'
    if family!='totw':
        binding=mapping.get('family_evidence',{}).get(family,{})
        if not binding.get('source_ids') or binding.get('basis')!='named_mobile_family_and_preserved_design':
            return 'no_historical_family_binding'
    key=record['record_id'];base=record['base_identity'];h=record['mobile_historical']
    if base.get('match_status')!='matched' or len(base.get('candidate_player_ids',[]))!=1:
        return 'unresolved_base_identity'
    card=card_index().get(base.get('preserved_base_resource_id'))
    if card is None or not card.lookup_supported or card.player_id!=base['candidate_player_ids'][0]:
        return 'unsupported_preserved_base'
    if record.get('special_resource_id') is not None:return 'non_base_resource_identity'
    if any(c.get('record_id')==key and c.get('type') in (
        'face_stats_conflict','special_rating_conflict','position_conflict','weekly_member_visual_family_unresolved',
        'historical_vs_preserved_base_quality') and c['type'] not in record.get('historical_version_review',{}).get('scoped_conflict_types',[]) for c in conflicts):return 'unresolved_field_conflict'
    if type(h.get('special_rating')) is not int or not 1<=h['special_rating']<=99:return 'missing_mobile_rating'
    position=record.get('position_reported')
    if position not in POSITION_WIRE.values():return 'missing_or_unsupported_position'
    keys=('DIV HAN KIC REF SPD POS' if position=='GK' else 'PAC SHO PAS DRI DEF PHY').split()
    stats=h.get('face_stats')
    if type(stats) is not dict or set(stats)!=set(keys) or any(type(stats[k]) is not int or not 0<=stats[k]<=99 for k in keys):
        return 'incomplete_mobile_stats'
    fields=record.get('field_provenance',{})
    if any(not fields.get(k) for k in ('mobile_membership','mobile_special_rating','mobile_face_stats','preserved_base_match')):
        return 'missing_mobile_field_provenance'
    observations=record.get('observations',[])
    # A direct Mobile observation supports the full canonical line; partial or
    # conflicting observations cannot be silently promoted to a reconstructed line.
    if not any(o.get('rating')==h['special_rating'] and o.get('position')==position and o.get('face_stats')==stats
               and o.get('visual_family') in mapping.get('observation_visuals',{}).get(family,('totw_black_gold','black_gold_stock_mobile') if family=='totw' else ()) for o in observations):
        return 'no_complete_mapped_mobile_observation'
    eligibility=record.get('revival_pack_eligibility',{})
    if (eligibility.get('base_quality_conflict') or eligibility.get('base_quality') not in ('gold','silver','bronze')
        or eligibility.get('base_rare') not in (0,1) or eligibility.get('base_rare')!=card.rare
        or eligibility.get('base_quality')!=card.quality):return 'unresolved_original_pack_family'
    return None


def resolve_source_club_identity(record):
    """Narrow review normalization; preserve the frozen original candidate list.

    An explicit source-club match can disambiguate an alias. The old research
    matcher retained its pre-club candidates even after marking a match; require
    the supplied supported-card intersection to independently select the stored
    identity before normalizing that cardinality for the existing review guard.
    """
    from .card_pool import card_index
    b=record['base_identity'];card=card_index().get(b.get('preserved_base_resource_id'))
    if (b.get('match_status')!='matched' or len(b.get('candidate_player_ids',[]))<=1
        or 'source_club_disambiguated' not in (b.get('match_method') or '')
        or not record.get('club_reported') or b.get('historical_club_matches_snapshot') is not True
        or card is None or not card.lookup_supported or card.team_id!=b.get('preserved_team_id')):
        return record
    candidates=sorted({c.player_id for c in card_index().values() if c.lookup_supported
                       and c.team_id==card.team_id and c.player_id in b['candidate_player_ids']})
    if candidates!=[card.player_id] or card.player_id!=b.get('preserved_base_low24_player_id'):return record
    reviewed=dict(record);base=dict(b);base['candidate_player_ids']=candidates;reviewed['base_identity']=base
    reviewed['identity_review']={'basis':'unique_supported_candidate_at_explicit_source_club',
        'original_candidate_player_ids':b['candidate_player_ids'],'resolved_player_id':card.player_id,
        'resource_id':card.resource_id,'source_club':record['club_reported'],'preserved_team_id':card.team_id,
        'master_unchanged':True}
    return reviewed

def historical_view(master,policy):
    """Enrich missing historical fields from explicitly reviewed image transcripts.

    The frozen master and base identities stay untouched. Conflicting non-null
    fields reject the supplement rather than silently replacing observations.
    Runtime approval remains a separate event/family prerequisite.
    """
    import copy
    if not policy.get('historical_observation_supplements') and not policy.get('historical_published_face_reviews'):return master
    view=copy.deepcopy(master);by_id={r['record_id']:r for r in view['special_records']}
    for definition in policy.get('historical_observation_supplements',[]):
        raw=(ROOT/definition['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=definition['sha256']:raise ValueError('Historical supplement changed; review required')
        data=json.loads(raw)
        if data.get('classification')!='mobile_historical_reconstruction' or data.get('master_unchanged') is not True:
            raise ValueError('Unreviewed historical supplement')
        seen=set()
        for o in data['observations']:
            key=o['record_id']
            if key in seen or key not in by_id:raise ValueError('Unknown/duplicate historical supplement record')
            seen.add(key);r=by_id[key];h=r['mobile_historical']
            if r['event_id']!=data['event_id'] or r['event_id'] not in definition['event_ids']:raise ValueError('Supplement event mismatch')
            sid=o['source']['source_id']
            if not o.get('mobile_membership_source') or not sid or not o['source'].get('sha256') or not o['source'].get('file'):
                raise ValueError('Supplement field provenance absent')
            for field,old,new in [('special_rating',h.get('special_rating'),o['rating']),('face_stats',h.get('face_stats'),o['face_stats']),('position',r.get('position_reported'),o['position'])]:
                if old is not None and old!=new:raise ValueError('Conflicting historical supplement '+field)
            h.update(special_rating=o['rating'],face_stats=o['face_stats']);r['position_reported']=o['position']
            r.setdefault('observations',[]).append({'source_id':sid,'rating':o['rating'],'position':o['position'],'face_stats':o['face_stats'],'visual_family':o['visual_family'],'formation_as_shown':o.get('formation_as_shown')})
            h['face_stats_semantics']='published_promotional_card_face'
            for field in ('mobile_membership','mobile_special_rating','mobile_face_stats'):
                r['field_provenance'][field]=sorted(set(r['field_provenance'].get(field,[])+[sid]))
            r['historical_supplement']={'path':definition['path'],'sha256':definition['sha256'],'classification':data['classification'],'record_id':key,'source':o['source'],'master_unchanged':True}
    for definition in policy.get('historical_published_face_reviews',[]):
        raw=(ROOT/definition['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=definition['sha256']:raise ValueError('Published face review changed')
        data=json.loads(raw)
        if data.get('classification')!='mobile_historical_reconstruction' or data.get('master_unchanged') is not True:raise ValueError('Unreviewed published scope')
        for sid,source in data['sources'].items():
            if sid not in master['sources'] or source['file']!=master['sources'][sid].get('file') or source['sha256']!=master['sources'][sid].get('sha256'):raise ValueError('Published source identity mismatch')
            if hashlib.sha256((ROOT/source['file']).read_bytes()).hexdigest()!=source['sha256']:raise ValueError('Published source changed')
        seen=set()
        for entry in data['reviews']:
            key=entry['record_id']
            if key in seen or key not in by_id:raise ValueError('Unknown/duplicate published version')
            seen.add(key);r=by_id[key];selected=set(entry['selected_source_ids'])
            if r['event_id']!=data['event_id'] or not selected or not selected<=data['sources'].keys():raise ValueError('Published scope mismatch')
            obs=[o for o in r['observations'] if o['source_id'] in selected and o.get('face_stats') is not None]
            faces={json.dumps({k:o[k] for k in ('rating','position','face_stats')},sort_keys=True) for o in obs}
            if len(faces)!=1 or json.dumps(entry['selected_face'],sort_keys=True) not in faces:raise ValueError('Contradictory or invented published face')
            if entry.get('other_observations')!=[o for o in r['observations'] if o['source_id'] not in data['sources']]:raise ValueError('Other observations must remain preserved')
            actual_types={c['type'] for c in master['conflicts'] if c.get('record_id')==key}
            if set(entry['scoped_conflict_types'])!=actual_types:raise ValueError('Conflict scope differs from recorded evidence')
            allowed={'face_stats_conflict','special_rating_conflict','position_conflict'}
            if not set(entry['scoped_conflict_types'])<=allowed:raise ValueError('Unsupported conflict scope')
            h=r['mobile_historical'];face=entry['selected_face']
            for field,old,new in [('rating',h.get('special_rating'),face['rating']),('stats',h.get('face_stats'),face['face_stats']),('position',r.get('position_reported'),face['position'])]:
                if old is not None and old!=new:raise ValueError('Published review contradicts canonical '+field)
            h.update(special_rating=face['rating'],face_stats=face['face_stats']);r['position_reported']=face['position']
            r['historical_version_review']={'path':definition['path'],'sha256':definition['sha256'],'scope':entry['scope'],
                'selected_source_ids':entry['selected_source_ids'],'scoped_conflict_types':entry['scoped_conflict_types'],
                'other_observations_preserved':True,'cause_of_owned_differences':'not inferred'}
    return view


@lru_cache(maxsize=1)
def review_index():
    from .mobile_special_catalog import index as mobile_index
    compiled = mobile_index()
    if compiled is not None:
        return compiled
    policy=json.loads(POLICY.read_text())
    if policy['classification'] not in ('revival_test','revival_policy') or policy['bulk_enabled'] is not False:
        raise ValueError('Unreviewed bulk special activation')
    raw=(ROOT/policy['master_path']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=policy['master_sha256']:raise ValueError('Historical master changed; review special policy')
    master=historical_view(json.loads(raw),policy);families={e['event_id']:e['family'] for e in master['events']}
    enums=json.loads((ROOT/'reports/special-card-audit/enum-assignments.json').read_text())
    if any(enums[scope]['TOTW_CARD']['value']!=3 for scope in ['main','patch']):raise ValueError('Unproven TOTW enum')
    approved=policy.get('reviewed_families',{})
    event_approvals=policy.get('reviewed_events',{})
    for approval in list(approved.values())+list(event_approvals.values()):
        mapping=policy['presentation_mappings'][approval['presentation_mapping']]
        if not mapping.get('runtime_proven',mapping.get('enum')=='TOTW_CARD') or not mapping.get('runtime_evidence'):
            raise ValueError('Family activation requires stock runtime/restart proof')
    for mapping in policy['presentation_mappings'].values():
        if (enums['patch'].get(mapping['enum'],{}).get('value')!=mapping['rareflag']
            or any(mapping['enum'] in enums[scope] and enums[scope][mapping['enum']]['value']!=mapping['rareflag'] for scope in ('main',))):
            raise ValueError('Presentation enum disagrees with supplied client')
    result={};excluded={}
    for r in sorted(master['special_records'],key=lambda r:r['record_id']):
        key=r['record_id'];family=families[r['event_id']]
        approval=policy['versions'].get(key) or event_approvals.get(r['event_id']) or approved.get(family)
        if approval is None:excluded[key]='unreviewed_family';continue
        mapping=policy['presentation_mappings'][approval['presentation_mapping']]
        if approval.get('identity_review')=='source_club_unique_supported_candidate':r=resolve_source_club_identity(r)
        reason=review_record(r,family,mapping,master['conflicts'])
        if reason:
            if key in policy['versions']:raise ValueError(f'Explicit version failed review: {key}: {reason}')
            excluded[key]=reason;continue
        h=r['mobile_historical'];position=r['position_reported']
        keys=('DIV HAN KIC REF SPD POS' if position=='GK' else 'PAC SHO PAS DRI DEF PHY').split()
        result[key]=SpecialVersion(key,r['base_identity']['preserved_base_resource_id'],h['special_rating'],position,
            tuple(h['face_stats'][k] for k in keys),mapping['rareflag'],
            {'classification':'mobile_historical_reconstruction','master_sha256':policy['master_sha256'],
             'field_sources':r['field_provenance'],'observations':r['observations'],
             'presentation_mapping':mapping,'identity_review':r.get('identity_review'),'historical_supplement':r.get('historical_supplement'),'historical_version_review':r.get('historical_version_review'),'approval_classification':policy['classification'],'runtime_review_status':'proven' if mapping.get('runtime_proven',mapping.get('enum')=='TOTW_CARD') else 'candidate'},r['revival_pack_eligibility'],family)
    tots_overlay=[];tots_excluded={}
    if policy.get('mobile_tots_supplement'):
        from .mobile_tots import reviewed_versions
        supplement,tots_excluded,tots_overlay=reviewed_versions(policy['presentation_mappings']['tots_11'],policy['mobile_tots_supplement'])
        result.update(supplement)
        for key in supplement:excluded.pop(key,None)
        for key,reason in tots_excluded.items():
            result.pop(key,None);excluded[key]=reason
    futties_overlay=[];futties_excluded={}
    if policy.get('mobile_futties_supplement'):
        from .mobile_futties import reviewed_versions as futties_versions
        supplement,futties_excluded,futties_overlay=futties_versions(policy['presentation_mappings']['futties_9'],policy['mobile_futties_supplement'])
        result.update(supplement);excluded.update(futties_excluded)
    console_excluded={}
    if policy.get('console_specials_supplement'):
        from .console_specials import reviewed_versions as console_versions
        supplement,console_excluded=console_versions(policy['presentation_mappings'],policy['console_specials_supplement'])
        # User rule: a console card is skipped only where an identical admitted Mobile version
        # (same base and overall) exists.
        mobile={(v.base_resource_id,v.rating) for v in result.values()}
        for key,v in supplement.items():
            if (v.base_resource_id,v.rating) in mobile:console_excluded[key]='identical_admitted_mobile_version'
            else:result[key]=v
        excluded.update(console_excluded)
    # Duplicate campaign membership is not evidence of independent numeric versions.
    # Collapse equal preserved identity/OVR/position/stats/style for pool weights,
    # retain all references and provenance for receipts and historical ownership.
    canonical={};aliases={}
    for key,v in result.items():
        fingerprint=(v.base_resource_id,v.rating,v.position,v.attributes,v.rareflag)
        first=canonical.setdefault(fingerprint,key)
        aliases[key]=first
    approved_event_ids={r['record_id'] for r in master['special_records'] if r['event_id'] in event_approvals}
    pool_ids=tuple(k for k in canonical.values() if (result[k].family in approved or k in approved_event_ids)
                   and result[k].provenance['runtime_review_status']=='proven')
    return {'versions':result,'excluded':excluded,'canonical_ids':tuple(canonical.values()),'pool_ids':pool_ids,'aliases':aliases,
            'master_sha256':policy['master_sha256'],'tots_overlay':tots_overlay,'tots_excluded':tots_excluded,'futties_overlay':futties_overlay,'futties_excluded':futties_excluded,
            'console_excluded':console_excluded}


def versions():return review_index()['versions']
# Existing callers may clear the provider cache for isolated policy tests.
versions.cache_clear=review_index.cache_clear

def reviewed_pool(quality=None,families=None):
    index=review_index()
    return tuple(index['versions'][k] for k in index['pool_ids']
                 if (quality is None or index['versions'][k].pack_eligibility['base_quality']==quality)
                 and (families is None or index['versions'][k].family in families))

def version(record_id):
    try:return versions()[record_id]
    except (KeyError,TypeError):raise ValueError('Unapproved reconstructed special version') from None

def validate_reference(item):
    if item.special_version_id is None:return
    if version(item.special_version_id).base_resource_id!=item.resource_id:
        raise ValueError('Special/base identity mismatch')

def player_version_key(item):
    key=item.special_version_id
    if key is not None:key=review_index()['aliases'][key]
    return item.resource_id,key

def display_rating(item):
    if item.special_version_id is not None:return version(item.special_version_id).rating
    from .local_content_source import rating_for
    return rating_for(item.resource_id)
