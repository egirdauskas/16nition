"""Locally verified content references only; no EA assets or player database.

The identifiers/links below are recovered by the read-only supplied DB reader
and tested by runs123/124. The catalog is separate from account ownership.
"""
from dataclasses import dataclass
import json
from pathlib import Path
CATALOG_PATH=Path(__file__).parent/'data/local-content-references.json'
@dataclass(frozen=True)
class ContentReference:
    resource_id:int
    card_subtype_id:int
    team_id:int
class ContentCatalog:
    def __init__(self,path=None):self.path=Path(path or CATALOG_PATH)
    def get(self,resource_id):
        if type(resource_id) is not int:raise ValueError('Invalid content reference')
        rows=json.loads(self.path.read_text())['references']
        row=next((r for r in rows if r['resource_id']==resource_id),None)
        if row is None:
            # Authorized revival packs may reference other shipped cards. The
            # source index validates exact resource/player/position/subtype
            # links; it never synthesizes a resource or upgrades a rating.
            from .card_pool import card_index
            card=card_index().get(resource_id)
            if card is None or not card.lookup_supported or card.packed_class!=7:
                raise ValueError('Content reference is absent/unsupported in supplied data')
            row={'resource_id':resource_id,'card_subtype_id':card.subtype,'team_id':card.team_id}
        ref=ContentReference(**row)
        if (type(ref.card_subtype_id) is not int or ref.card_subtype_id not in range(4)
            or type(ref.team_id) is not int or not 0<ref.team_id<=200000):
            raise ValueError('Invalid verified content link')
        return ref
