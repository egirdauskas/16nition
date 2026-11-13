"""Official Mobile FUTTIES identity/OVR with separate, authorized revival fields.

Pink9 is a proposed local presentation, not an original EA wire reconstruction.
No live-pool admission precedes independent stock/restart certification.
"""
import hashlib,json
from pathlib import Path
from .mobile_tots import resolve_stats
ROOT=Path(__file__).resolve().parents[1]
POLICY=Path(__file__).parent/'policy/futties-stats-synthesis.json'
EVIDENCE=ROOT/'reports/special-conversion-pass/futties/historical-evidence.json'
def reviewed_versions(mapping,config):
 from .card_pool import card_index
 from .reconstructed_specials import SpecialVersion
 if mapping.get('rareflag')!=9 or mapping.get('enum')!='PINK_CARD' or mapping.get('assignment_provenance')!='revival_policy_authorized':
  raise ValueError('FUTTIES requires explicitly authorized pink presentation')
 raw=EVIDENCE.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=config['historical_evidence_sha256']:raise ValueError('FUTTIES evidence changed; rebuild review')
 if hashlib.sha256(POLICY.read_bytes()).hexdigest()!=config['synthesis_policy_sha256']:raise ValueError('FUTTIES policy changed; rebuild review')
 evidence=json.loads(raw);result={};excluded={};overlay=[];seen=set()
 for r in evidence['records']:
  key=r['special_version_id']
  if key in seen:raise ValueError('Duplicate FUTTIES version')
  seen.add(key);card=card_index().get(r.get('base_resource_id'));reason=None
  if r.get('conflicts'):reason='unresolved_authentic_field_conflict'
  elif r.get('classification')!='ea_first_party_confirmed' or r.get('source_announcement_ids')!=['5471946']:reason='not_confirmed_mobile_futties'
  elif r.get('match_status')!='matched' or card is None or not card.lookup_supported:reason='unresolved_or_unsupported_base'
  elif r.get('base_match',{}).get('candidate_player_ids')!=[card.player_id]:reason='ambiguous_base_identity'
  if reason:excluded[key]=reason;continue
  try:resolved=resolve_stats(r,policy_path=POLICY)
  except ValueError as e:excluded[key]=str(e);continue
  keys=('DIV HAN KIC REF SPD POS' if r['position']=='GK' else 'PAC SHO PAS DRI DEF PHY').split()
  eligibility={'policy_class':'revival_policy','base_quality':card.quality,'base_rare':card.rare,'permanently_packable':True,
   'historical_release_window_ignored':True,'special_rating_does_not_rebucket':True,'special_style_does_not_rebucket':True,
   'base_quality_conflict':False,'resolved_pack_families':[card.quality],'basis':'preserved_base_snapshot'}
  result[key]=SpecialVersion(key,card.resource_id,r['mobile_ovr'],r['position'],tuple(resolved['effective_six_stats'][k] for k in keys),9,
   {'classification':'mobile_historical_reconstruction_with_revival_policy','field_sources':r['field_provenance'],
    'presentation_mapping':mapping,'presentation_provenance':'revival_policy_authorized',
    'runtime_review_status':'proven' if mapping.get('runtime_proven') else 'candidate','stats_provenance':resolved['stats_provenance'],
    'revival_stats_overlay':resolved,'historical_record_id':r['historical_record_id'],'source_announcement_ids':r['source_announcement_ids']},eligibility,'futties')
  overlay.append(resolved)
 return result,excluded,overlay
