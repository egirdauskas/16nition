"""One typed Club player query over owned items and supplied content references.

Both Inventory and Swap with Club use the same ClubSearch record decoder. Do
not whitelist a particular position, club or league, or use native cache items
as ownership. Filters compose before stable sorting and pagination.
"""
from dataclasses import dataclass
from functools import lru_cache
from .local_content_source import DB, META, cards, POSITION_WIRE, position_for
from .local_formations import FORMATIONS
from .local_football import item_pile
from .reconstructed_specials import display_rating, version

# Original collection types26/27/28 (FutServerTypesDefinition.lua), with
# literal URLs in libfifa.so. The same position families serve Market filters.
PLAYER_TYPES = {
    'player': None,
    'playerdefender': 'defense',
    'playermidfielder': 'midfield',
    'playerforward': 'attacker',
}


@lru_cache(maxsize=1)
def content_filters():
    from scripts.local_football_db import FootballDB
    cards()  # Verify preserved DB and metadata before reading references.
    db = FootballDB(DB, META)
    def rows(table, fields):
        limit = db.table(table)['valid_count']
        return [r for r in db.rows(table, fields) if r['row_index'] < limit]
    nations = {r['playerid']: r['nationality'] for r in rows('players', ['playerid', 'nationality'])}
    teams = frozenset(r['teamid'] for r in rows('teams', ['teamid']))
    leagues = {}
    for r in rows('futleagueteamlinks', ['teamid', 'leagueid']):
        leagues.setdefault(r['leagueid'], set()).add(r['teamid'])
    return nations, teams, {k: frozenset(v) for k, v in leagues.items() if k > 0}


def integer(value, minimum, maximum):
    result = int(value)
    if str(result) != value or not minimum <= result <= maximum:
        raise ValueError('Noncanonical Club query integer')
    return result


@dataclass(frozen=True)
class PlayerQuery:
    count: int
    start: int = 0
    sort: str = 'desc'
    level: str = 'any'
    position: str | None = None
    formation: int | None = None
    nation: int = -1
    league: int = -1
    team: int = -1
    untradeable: bool | None = None
    player_type: str = 'player'

    @classmethod
    def decode(cls, query):
        required = {'type', 'count'}
        allowed = required | {'sort', 'level', 'position', 'formation', 'nation', 'league', 'team', 'start', 'state', 'untradeable'}
        if (not required <= query.keys() or query.keys() - allowed or
                any(len(v) != 1 for v in query.values()) or query['type'][0] not in PLAYER_TYPES):
            raise ValueError('Unknown or duplicate Club player filter')
        q = {k: v[0] for k, v in query.items()}
        # ConstructSquad886 omits Any level and requests the free Club pool.
        # Club-pile ownership already excludes unassigned and transfer custody;
        # the original builder handles its target-squad/Replace selection itself.
        q.setdefault('level', 'any')
        # Genuine squad role picker omits sort (9 Nov midfielder request).
        q.setdefault('sort', 'desc')
        if 'state' in q and q['state'] != 'free':
            raise ValueError('Unknown Club ownership state selector')
        if q['level'] not in ('any', 'bronze', 'silver', 'gold') or q['sort'] not in ('asc', 'desc'):
            raise ValueError('Unknown Club level or sort')
        # Original PlayerExchange1337 asks count58/sortasc/untradeable=false.
        # Filter authoritative ownership before sorting/paging; do not expose
        # reward cards merely because the general Club picker can display them.
        untradeable = None
        if 'untradeable' in q:
            if q['untradeable'] not in ('true', 'false'):
                raise ValueError('Unknown Club tradeability filter')
            untradeable = q['untradeable'] == 'true'
        position = q.get('position')
        if position is not None and position not in POSITION_WIRE.values():
            raise ValueError('Unknown supplied position')
        formation = None
        if 'formation' in q:
            formation = next((i for i, wire in FORMATIONS.items() if wire == q['formation']), None)
            if formation is None:
                raise ValueError('Unknown supplied formation')
        nation, league, team = (integer(q.get(k, '-1'), -1, 0x7fffffff) for k in ('nation', 'league', 'team'))
        nations, teams, leagues = content_filters()
        if (nation > 0 and nation not in nations.values() or
                league > 0 and league not in leagues or team > 0 and team not in teams):
            raise ValueError('Unknown supplied nationality, league or club')
        # Native counts/offsets are signed integers. The result is naturally
        # bounded by this account's owned collection, not by a fixture page size.
        return cls(integer(q['count'], 1, 0x7fffffff), integer(q.get('start', '0'), 0, 0x7fffffff),
                   q['sort'], q['level'], position, formation, nation, league, team,
                   untradeable, q['type'])

    def select(self, state, catalog):
        nations, _, leagues = content_filters()
        from .market_search import ZONES
        group = PLAYER_TYPES[self.player_type]
        found = []
        for item in state.owned_items:
            if item_pile(state, item.instance_id) != 'club':
                continue
            if self.untradeable is not None and (item.instance_id in state.untradeable_instance_ids) != self.untradeable:
                continue
            ref = catalog.get(item.resource_id)
            rating = display_rating(item)
            quality = 'gold' if rating >= 75 else 'silver' if rating >= 65 else 'bronze'
            from .consumable_effects import effective_position
            position = effective_position(item)
            if (self.level != 'any' and quality != self.level or
                    group is not None and position not in ZONES[group] or
                    self.position is not None and position != self.position or
                    self.formation is not None and item.formation_id != self.formation or
                    self.nation > 0 and nations[item.resource_id & 0xffffff] != self.nation or
                    self.league > 0 and ref.team_id not in leagues[self.league] or
                    self.team > 0 and ref.team_id != self.team):
                continue
            found.append(item)
        found.sort(key=lambda i: (display_rating(i), i.instance_id), reverse=self.sort == 'desc')
        return found[self.start:self.start + self.count]
