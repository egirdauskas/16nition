"""Original supplied text plus separately labeled user-defined specialist captions."""
import json
from functools import lru_cache
from pathlib import Path
PATH=Path(__file__).parent/'policy/recovered-pack-captions-v1.json'

@lru_cache(maxsize=1)
def recovered():
 value=json.loads(PATH.read_text())
 if value['version']!='recovered_pack_captions_v1' or value['classification']!='recovered_supplied_stock_text':raise ValueError('Unsupported original caption provenance')
 player=json.loads(PATH.with_name('recovered-player-pack-captions-v1.json').read_text())
 if player['version']!='recovered_player_pack_captions_v1' or player['classification']!='recovered_supplied_stock_text':raise ValueError('Unsupported original player caption provenance')
 if value['definitions'].keys() & player['definitions'].keys():raise ValueError('Cannot replace an existing caption binding')
 extra=json.loads(PATH.with_name('recovered-player-pack-captions-v2.json').read_text())
 if extra['version']!='recovered_player_pack_captions_v2' or extra['classification']!='recovered_supplied_stock_text':raise ValueError('Unsupported extended player caption provenance')
 if (value['definitions'].keys() | player['definitions'].keys()) & extra['definitions'].keys():raise ValueError('Cannot replace an existing player caption binding')
 large=json.loads(PATH.with_name('recovered-large-pack-captions-v1.json').read_text())
 if large['version']!='recovered_large_pack_captions_v1' or large['classification']!='recovered_supplied_stock_text':raise ValueError('Unsupported large pack caption provenance')
 existing={**value['definitions'],**player['definitions'],**extra['definitions']}
 if existing.keys() & large['definitions'].keys():raise ValueError('Cannot replace an existing large pack caption binding')
 existing={**existing,**large['definitions']}
 for filename,version,classification in (
  ('recovered-player-pack-captions-v3.json','recovered_player_pack_captions_v3','recovered_supplied_stock_text'),
  ('recovered-ultimate-pack-caption-v1.json','recovered_ultimate_pack_caption_v1','recovered_original_ea_console_text')):
  extra=json.loads(PATH.with_name(filename).read_text())
  if extra['version']!=version or extra['classification']!=classification:raise ValueError('Unsupported remaining pack caption provenance')
  if existing.keys() & extra['definitions'].keys():raise ValueError('Cannot replace an existing caption binding')
  existing.update(extra['definitions'])
 return existing

def display_name(name):
 """User (7 Nov 2026): no all-caps pack titles. Display-only: definitions, captions and their
 gates keep the recovered/approved names; an all-caps title is written in title case."""
 if not isinstance(name,str) or name!=name.upper() or not any(c.isalpha() for c in name):return name
 return ' '.join(word.capitalize() for word in name.split(' '))

def captions(definition):
 from .store_demo_offers import captions as demo_captions
 demo = demo_captions(definition)
 if demo is not None:
  return demo
 from .store_single_captions import captions as single_captions
 single = single_captions(definition)
 if single is not None:
  return single
 from .pack_family_split import captions as split_captions
 split=split_captions(definition)
 if split is not None:return split
 from .standard_pack_specs import captions as spec_captions,caption_origin
 updated=spec_captions(definition)
 if updated is not None:return updated
 definition=caption_origin(definition)
 from .specialist_consumable_packs import captions as specialist_captions
 custom=specialist_captions(definition)
 if custom is not None:return custom
 from .pack_policy import PATH
 club=json.loads(PATH.with_name('club-item-pack-bindings-v1.json').read_text())['bindings']
 definition=next((r['previous_definition'] for r in club.values() if r['definition']==definition),definition)
 crowd=json.loads(PATH.with_name('filtered-consumable-pack-bindings-v2.json').read_text())['bindings']
 definition=next((r['previous_definition'] for r in crowd.values() if r['definition']==definition),definition)
 filtered=json.loads(PATH.with_name('filtered-consumable-pack-bindings-v1.json').read_text())['bindings']
 definition=next((r['previous_definition'] for r in filtered.values() if r['definition']==definition),definition)
 expanded=json.loads(PATH.with_name('expanded-consumable-pack-bindings-v1.json').read_text())['bindings']
 definition=next((r['previous_definition'] for r in expanded.values() if r['definition']==definition),definition)
 bindings=json.loads(PATH.with_name('all-tier-special-pack-bindings-v1.json').read_text())['bindings']
 definition=next((r['previous_definition'] for r in bindings.values() if r['definition']==definition),definition)
 row=recovered().get(definition)
 if row is None:return None
 return {kind:entry['value'] if entry is not None else '' for kind,entry in row.items()}
