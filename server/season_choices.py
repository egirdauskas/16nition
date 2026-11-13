"""Versioned revival Seasons catalog; historical prizes never drive grants.

Pure catalog, eligibility and supplied-club fixture selection. No client field
names, account writes or reward paths are inferred from the historical guides.
"""
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import json
import re

POLICY = Path(__file__).parent / 'policy/offline-season-choices-v1.json'
VERSION = 'offline_season_choices_v1'
DIFFICULTIES = {'B': 0, 'A': 1, 'S': 2, 'P': 3, 'W': 4, 'L': 5, 'U': 6}
RULE_KINDS = {'chemistry', 'distinct_nationalities', 'players_sharing_league',
              'players_from_named_league'}


def _int(value, lower, upper):
    return type(value) is int and lower <= value <= upper


def validate_rule(rule):
    if type(rule) is not dict or rule.get('kind') not in RULE_KINDS:
        raise ValueError('Unknown Seasons eligibility rule')
    expected = {'kind', 'operator', 'value'}
    if rule['kind'] != 'chemistry': expected.add('scope')
    if rule['kind'] == 'players_from_named_league': expected.add('league_id')
    if set(rule) != expected or rule['operator'] not in ('>=', '=='):
        raise ValueError('Invalid Seasons eligibility predicate')
    if not _int(rule['value'], 1, 100 if rule['kind'] == 'chemistry' else 18):
        raise ValueError('Invalid Seasons eligibility bound')
    if rule['kind'] != 'chemistry' and rule['scope'] not in ('starting11', 'starting11_and_substitutes'):
        raise ValueError('Unsupported Seasons squad scope')
    if rule['kind'] == 'players_from_named_league' and not _int(rule['league_id'], 1, 10000):
        raise ValueError('Invalid supplied league reference')
    return rule


@dataclass(frozen=True)
class Competition:
    key: str
    division: int
    name: str
    opponent_league_id: int | None
    rules_json: str
    difficulty_codes: str
    historical_reference_json: str

    @property
    def rules(self): return json.loads(self.rules_json)

    @property
    def historical_reference(self): return json.loads(self.historical_reference_json)

    @property
    def difficulties(self): return tuple(DIFFICULTIES[x] for x in self.difficulty_codes)


from .local_seasons import CompetitionDefinition


@dataclass(frozen=True)
class ChoiceDefinition(CompetitionDefinition):
    """New definitions only; legacy definitions/fixture snapshots stay exact."""
    choices_version: str
    competition_key: str
    fixture_seed: str
    catalog_sha256: str

    def validate(self):
        catalog = load_catalog()
        if (self.choices_version != VERSION or self.competition_key not in catalog
                or self.catalog_sha256 != sha256(POLICY.read_bytes()).hexdigest()):
            raise ValueError('Unknown or changed selected competition policy')
        c = catalog[self.competition_key]
        if (not _int(self.season_id, 1, 1024) or type(self.division_index) is not int
                or self.division_index != c.division or type(self.match_minutes) is not int
                or self.match_minutes != 6):
            raise ValueError('Selected competition identity/format mismatch')
        if (any(type(f.team_id) is not int or type(f.difficulty) is not int
                or type(f.round_number) is not int for f in self.fixtures)
                or self.fixtures != fixtures(c, self.fixture_seed)):
            raise ValueError('Selected competition fixtures differ from pinned policy')
        return self


def definition(competition, season_id, seed):
    return ChoiceDefinition(season_id, competition.division, 6, fixtures(competition, seed),
                            VERSION, competition.key, seed, sha256(POLICY.read_bytes()).hexdigest()).validate()


def load_catalog(path=POLICY):
    # Bytes are read on every use: policy edits still validate/refuse promptly.
    # Entries are frozen and nested fields are JSON strings. Return a fresh map
    # so a caller cannot alter the cached catalog used by another request.
    return dict(_catalog_from_bytes(Path(path).read_bytes()))


@lru_cache(maxsize=8)
def _catalog_from_bytes(raw):
    data = json.loads(raw)
    if (data.get('version') != VERSION or data.get('classification') != 'revival_policy'
            or data.get('enabled_by_default') is not False
            or data.get('runtime_rewards') != 'unchanged_existing_division_policy'):
        raise ValueError('Unsupported Seasons catalog or reward activation')
    result = {}
    for row in data['competitions']:
        key = row['key']
        if (type(key) is not str or re.fullmatch(r'd[1-9][0-9]?_[a-z0-9_]+', key) is None
                or key in result or not _int(row['division'], 1, 10)
                or not key.startswith(f"d{row['division']}_") or not row['name']):
            raise ValueError('Invalid or duplicate Seasons identity')
        if row['opponent_league_id'] is not None and not _int(row['opponent_league_id'], 1, 10000):
            raise ValueError('Invalid opponent league')
        levels = row['difficulty_codes']
        if type(levels) is not str or len(levels) != 10 or not set(levels) <= DIFFICULTIES.keys():
            raise ValueError('Ten supported difficulty values required')
        for rule in row['rules']: validate_rule(rule)
        if row['historical_reference'].get('reference_only') is not True:
            raise ValueError('Historical prize references must not become grants')
        result[key] = Competition(key, row['division'], row['name'], row['opponent_league_id'],
                                  json.dumps(row['rules'], sort_keys=True), levels,
                                  json.dumps(row['historical_reference'], sort_keys=True))
    counts = [sum(c.division == d for c in result.values()) for d in range(10, 0, -1)]
    if counts != [4, 4, 4, 5, 5, 5, 5, 5, 5, 7]:
        raise ValueError('Complete selected 49-competition catalog required')
    return tuple(result.items())


def for_division(division, catalog=None):
    if not _int(division, 1, 10): raise ValueError('Invalid Seasons division')
    return tuple(c for c in (catalog if catalog is not None else load_catalog()).values()
                 if c.division == division)


@lru_cache(maxsize=1)
def supplied_facts():
    from .local_content_source import cards, DB, META
    from scripts.local_football_db import FootballDB
    cards()  # Existing frozen DB/meta integrity check.
    db = FootballDB(DB, META)
    def valid_rows(table, fields):
        count = db.table(table)['valid_count']
        return (r for r in db.rows(table, fields) if r['row_index'] < count)
    nations = {r['playerid']: r['nationality'] for r in valid_rows('players', ['playerid', 'nationality'])}
    league_ids = {r['leagueid'] for r in valid_rows('leagues', ['leagueid'])}
    teams = {}
    for row in valid_rows('futleagueteamlinks', ['teamid', 'leagueid']):
        if row['leagueid'] in league_ids: teams.setdefault(row['teamid'], set()).add(row['leagueid'])
    return nations, {k: frozenset(v) for k, v in teams.items()}


def player_facts(item):
    from .card_pool import card_index
    from .reconstructed_specials import validate_reference
    validate_reference(item)
    card = card_index().get(item.resource_id)
    if card is None or not card.lookup_supported: raise ValueError('Unsupported owned player reference')
    nations, teams = supplied_facts()
    nation, leagues = nations.get(card.player_id), teams.get(card.team_id)
    if type(nation) is not int or nation <= 0 or not leagues:
        raise ValueError('Owned player has no supported eligibility facts')
    return {'nation': nation, 'leagues': leagues}


def evaluate(competition, football, *, facts=player_facts):
    """Evaluate actual selected-squad ownership; missing evidence cannot pass.

    Squad chemistry is the existing persisted stock-calculated squad summary;
    do not invent a competing chemistry calculation. Slots0..10 are starters,
    11..17 substitutes, and18..22 reserves (excluded from these guide scopes).
    """
    if type(competition) is not Competition: raise ValueError('Validated competition required')
    failures = []
    owned = {item.instance_id: item for item in football.owned_items}
    lineup = {slot.index: slot.instance_id for slot in football.active_lineup}
    for rule in competition.rules:
        validate_rule(rule)
        measured = None
        reason = None
        if rule['kind'] == 'chemistry':
            if football.squad_summary is None: reason = 'missing_stock_chemistry'
            else: measured = football.squad_summary.chemistry
        else:
            if any(i not in lineup or lineup[i] not in owned for i in range(11)):
                reason = 'incomplete_starting11'
            else:
                end = 11 if rule['scope'] == 'starting11' else 18
                try:
                    selected = [facts(owned[lineup[i]]) for i in range(end) if i in lineup]
                    if rule['kind'] == 'distinct_nationalities':
                        measured = len({p['nation'] for p in selected})
                    elif rule['kind'] == 'players_sharing_league':
                        leagues = {league for p in selected for league in p['leagues']}
                        measured = max((sum(league in p['leagues'] for p in selected) for league in leagues), default=0)
                    else:
                        measured = sum(rule['league_id'] in p['leagues'] for p in selected)
                except (KeyError, ValueError): reason = 'unsupported_player_facts'
        if reason is None:
            if not _int(measured, 0, 100): reason = 'invalid_squad_measurement'
            elif not (measured >= rule['value'] if rule['operator'] == '>=' else measured == rule['value']):
                reason = 'requirement_not_met'
        if reason:
            failures.append({'rule': rule, 'reason': reason, 'measured': measured})
    return {'competition_key': competition.key, 'eligible': not failures, 'failures': failures,
            'classification': 'revival_policy', 'rewards_changed': False}


def opponent_pool(competition):
    from .season_content import eligible_team_ids
    _, teams = supplied_facts()
    if competition.opponent_league_id is None:
        # Clubs only: supplied international and beta-test teams are excluded.
        ids = {team for team, leagues in teams.items() if leagues - {78, 123}}
    else:
        ids = {team for team, leagues in teams.items() if competition.opponent_league_id in leagues}
    result = frozenset(ids & eligible_team_ids())
    if len(result) < 10: raise ValueError('Insufficient coherent supplied opponents')
    return result


@lru_cache(maxsize=128)
def _ordered_teams(version, competition_key, seed, pool):
    """Cache only immutable supplied-pool ordering, never account/reward state."""
    def order(team):return sha256(json.dumps([version,competition_key,seed,team],separators=(',',':')).encode()).digest(),team
    return tuple(sorted(pool,key=order)[:10])


def fixtures(competition, seed):
    """Local deterministic order within a supplied pool; never historical scores.

    The caller must persist seed and definition with the original season anchor.
    This pure function cannot replace any active account definition or journal.
    """
    from .local_seasons import Fixture
    if type(seed) is not str or not 1 <= len(seed) <= 128: raise ValueError('Explicit fixture seed required')
    teams = _ordered_teams(VERSION,competition.key,seed,opponent_pool(competition))
    return tuple(Fixture(team, difficulty, i) for i, (team, difficulty) in
                 enumerate(zip(teams, competition.difficulties), 1))
