"""Transfer Market search request decoding and reply (MARKET-001).

Native URL builder 023089b8: `transfermarket?type=%s&start=%d&num=%d` plus
optional predicates. Only predicates with a genuine wire capture are admitted;
any other parameter leaves the request unanswered (held) until captured.
"""

from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from .game_auth import SID
from .identity import json_response

ROUTE = '/ut/game/fifaworldmobile/transfermarket'
# Captured: 415/416 default and leag=13; 1401 lev=gold, zone=defense, pos=CB,
# micr/macr/minb/maxb, nat=97, form=f3421, leag=13&team=5, zone=midfield/attacker.
CAPTURED = {'type', 'start', 'num', 'leag', 'lev', 'zone', 'pos', 'nat', 'team', 'form',
            'micr', 'macr', 'minb', 'maxb', 'cat'}
# 1413 Staff Type picker. Only managers have market supply (user direction:
# no coach/physio search); the others answer an honest empty list.
STAFF_CATEGORIES = {'manager', 'headCoach', 'GKCoach', 'fitnessCoach', 'physio'}
LEVELS = {'bronze', 'silver', 'gold'}
# 1406/1408 captured the original non-player categories. There is no non-player
# supply in the admitted market: finish these reads with an honest empty result
# instead of letting the native UI time out with TRANSFER ISSUE.
ITEM_TYPES = {'player', 'ball', 'stadium', 'clubInfo', 'staff'}
CLUB_INFO_KINDS = ('kit', 'badge')
# Zones captured in 1401 (Position picker Defender/Midfielder/Attacker); GK is its own position.
ZONES = {
    'defense': {'CB', 'LB', 'RB', 'LWB', 'RWB'},
    'midfield': {'CDM', 'CM', 'CAM', 'LM', 'RM'},
    'attacker': {'ST', 'CF', 'LF', 'RF', 'LW', 'RW'},
}
POSITIONS = {'GK', 'RWB', 'RB', 'CB', 'LB', 'LWB', 'CDM', 'RM', 'CM', 'LM', 'CAM',
             'RF', 'CF', 'LF', 'RW', 'ST', 'LW'}


def canonical_int(text, low, high):
    value = int(text)
    if str(value) != text or not low <= value <= high:
        raise ValueError('Noncanonical market query integer')
    return value


@dataclass(frozen=True)
class Query:
    start: int
    num: int
    league: int | None = None
    level: str | None = None
    zone: str | None = None
    position: str | None = None
    nation: int | None = None
    team: int | None = None
    formation: str | None = None
    min_bid: int | None = None
    max_bid: int | None = None
    min_buy_now: int | None = None
    max_buy_now: int | None = None
    item_type: str = 'player'
    staff_category: str | None = None
    club_kind: str | None = None

    @classmethod
    def decode(cls, target):
        from .local_formations import FORMATIONS

        url = urlsplit(target)
        if url.path != ROUTE:
            raise ValueError('Not a market search')
        query = parse_qs(url.query, keep_blank_values=True)
        if any(len(v) != 1 for v in query.values()) or not {'type', 'start', 'num'} <= query.keys():
            raise ValueError('Malformed market search')
        if query.keys() - CAPTURED:
            raise ValueError('Uncaptured market predicate')
        if query['type'][0] not in ITEM_TYPES:
            raise ValueError('Uncaptured market item type')
        one = {name: values[0] for name, values in query.items()}
        if one['type'] == 'player' and 'cat' in one:
            raise ValueError('Category belongs to staff searches')
        if one['type'] != 'player':
            allowed = {'type', 'start', 'num', 'micr', 'macr', 'minb', 'maxb'}
            if one['type'] == 'staff':
                allowed.add('cat')
                if one.get('cat', 'manager') not in STAFF_CATEGORIES:
                    raise ValueError('Unknown staff category')
            if one['type'] == 'clubInfo':
                # Genuine 4 Nov 2026 stock requests: cat=kit / cat=badge.
                allowed.add('cat')
                if one.get('cat', 'kit') not in CLUB_INFO_KINDS:
                    raise ValueError('Unknown club item category')
            if query.keys() - allowed:
                raise ValueError('Uncaptured non-player filter')

        def number(name, high=10**9):
            return canonical_int(one[name], 1, high) if name in one else None

        if 'lev' in one and one['lev'] not in LEVELS:
            raise ValueError('Unknown level')
        if 'zone' in one and one['zone'] not in ZONES:
            raise ValueError('Uncaptured zone')
        if 'pos' in one and one['pos'] not in POSITIONS:
            raise ValueError('Unknown position')
        if 'form' in one and one['form'] not in FORMATIONS.values():
            raise ValueError('Unknown formation')
        if 'team' in one and 'leag' not in one:
            raise ValueError('Club filter arrives with its league')
        return cls(
            canonical_int(one['start'], 0, 10**6), canonical_int(one['num'], 1, 100),
            league=number('leag', 10**6), level=one.get('lev'), zone=one.get('zone'),
            position=one.get('pos'), nation=number('nat', 10**6), team=number('team', 10**9),
            formation=one.get('form'), min_bid=number('micr'), max_bid=number('macr'),
            min_buy_now=number('minb'), max_buy_now=number('maxb'),
            item_type=one['type'],
            staff_category=one.get('cat') if one['type'] == 'staff' else None,
            club_kind=one.get('cat') if one['type'] == 'clubInfo' else None,
        )

    def item_supply(self):
        """Whether this non-player search has bot supply (policy v1; managers only for staff)."""
        from .market_economy import items_enabled
        if not items_enabled():
            return False
        return self.item_type != 'staff' or self.staff_category in (None, 'manager')

    def matches(self, listing):
        from .card_pool import card_index
        from .local_formations import FORMATIONS
        from .market_economy import facts

        item = listing['item']
        if self.item_type != 'player':
            if self.club_kind is not None and item.get('kind') != self.club_kind:
                return False
            return self.price_matches(listing)
        card = facts(item['resource_id'], item.get('special_version_id'))
        position = item.get('preferred_position') or card.position
        if self.league is not None and card.league != self.league:
            return False
        if self.team is not None and card_index()[item['resource_id']].team_id != self.team:
            return False
        if self.level is not None and card.quality != self.level:
            return False
        if self.zone is not None and position not in ZONES[self.zone]:
            return False
        if self.position is not None and position != self.position:
            return False
        if self.nation is not None and card.nation != self.nation:
            return False
        if self.formation is not None:
            from .market_store import item_formation
            formation = item_formation(listing)
            if formation is None or FORMATIONS[formation] != self.formation:
                return False
        return self.price_matches(listing)

    def price_matches(self, listing):
        bid = listing['current_bid'] or listing['starting_bid']
        if self.min_bid is not None and bid < self.min_bid:
            return False
        if self.max_bid is not None and bid > self.max_bid:
            return False
        if self.min_buy_now is not None and listing['buy_now'] < self.min_buy_now:
            return False
        if self.max_buy_now is not None and listing['buy_now'] > self.max_buy_now:
            return False
        return True


def response_for(method, target, headers, body, account):
    if (method != 'GET' or body or headers.get(b'host') != b'10.0.2.2:18081'
            or headers.get(b'x-ut-sid') != SID.encode() or headers.get(b'content-length', b'0') != b'0'):
        return None
    try:
        query = Query.decode(target)
    except ValueError:
        return None
    from .market_store import search
    return json_response(search(account, query))
