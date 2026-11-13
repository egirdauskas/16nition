"""Read-only shipped-card index. Full resource keys never collapse variants.

Classification comes from supplied fcc_playercards and packed resource bits;
Gold >=75 is an explicit revival_policy eligibility choice, not stock odds.
No names, ratings or other static content are written into account state.
"""
from dataclasses import dataclass
from functools import lru_cache
from .local_content_source import cards, DB, META, POSITION_WIRE
from scripts.local_football_db import FootballDB

@dataclass(frozen=True)
class Card:
    resource_id: int
    player_id: int
    rating: int
    rare: int
    subtype: int
    team_id: int
    preferred_position: int
    packed_class: int
    variant_bits: int
    source_row: int
    lookup_supported: bool

    @property
    def quality(self):
        return 'gold' if self.rating >= 75 else 'silver' if self.rating >= 65 else 'bronze'
    @property
    def variant(self):
        return 'base' if self.variant_bits == 0 else 'shipped_special_variant'

@lru_cache(maxsize=1)
def card_index():
    cards()  # Verify preserved DB/meta hashes before reading any row.
    db = FootballDB(DB, META)
    players = {r['playerid'] for r in db.rows('players',['playerid'])}
    teams = {r['teamid'] for r in db.rows('teams',['teamid'])}
    league_teams = {r['teamid'] for r in db.rows('futleagueteamlinks',['teamid','leagueid']) if r['leagueid']>0}
    limit = db.table('fcc_playercards')['valid_count']
    result = {}
    for row in db.rows('fcc_playercards',['carddbid','rating','rare','fieldpos','teamid','preferredposition']):
        if row['row_index'] >= limit: continue
        rid = row['carddbid']; player = rid & 0xffffff
        if rid in result: raise ValueError('Duplicate supplied resource identity')
        result[rid] = Card(rid, player, row['rating'], row['rare'],row['fieldpos'],row['teamid'],
            row['preferredposition'], (rid>>28)&15,(rid>>24)&15,row['row_index'],
            player in players and row['preferredposition'] in POSITION_WIRE and row['fieldpos'] in range(4)
            and row['teamid'] in teams and row['teamid'] in league_teams and 0<row['rating']<=99)
    return result

def gold_pool():
    return tuple(c for c in card_index().values() if c.quality=='gold' and c.lookup_supported)
