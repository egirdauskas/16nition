"""Authorised console fallback catalog; original Mobile protocol is separate.

Historical prizes are references, not grants. Metadata service keys identify
downloaded captions/art, never owned trophy/card resources. No account writes.
"""
from dataclasses import dataclass
import copy
import hashlib
import json
import re
from pathlib import Path
from .season_content import eligible_team_ids

PATH=Path(__file__).parent/'policy/offline-tournament-catalog-v1.json'
EXTENDED_PATH = PATH.with_name('offline-tournament-catalog-v2.json')
_CATALOG_CACHE = {}


@dataclass(frozen=True)
class Cup:
    key:str
    name:str
    service_id:int
    metadata_service_id:int
    difficulty:int
    required_quality:str|None
    quality_scope:str
    minimum_chemistry:int
    unlock_trophies:int
    historical_prize_json:str
    trophy_asset:str
    trophy_silhouette:str
    minimum_brazilian_starters: int = 0
    minimum_five_star_skillers: int = 0

    @property
    def historical_prize_reference(self):return json.loads(self.historical_prize_json)


def load_catalog(path=PATH):
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).digest()
    if digest in _CATALOG_CACHE:
        return copy.deepcopy(_CATALOG_CACHE[digest])
    result = _parse_catalog(raw)
    if len(_CATALOG_CACHE) >= 8:
        _CATALOG_CACHE.clear()
    _CATALOG_CACHE[digest] = result
    return copy.deepcopy(result)


def _parse_catalog(raw):
    value = json.loads(raw)
    extended = value.get('version') == 'offline_tournament_catalog_v2'
    classification = 'revival_policy_extended_tournaments' if extended else 'revival_policy_console_fallback'
    count = 5 if extended else 4
    if (value.get('version') not in ('offline_tournament_catalog_v1', 'offline_tournament_catalog_v2') or
            value.get('classification') != classification or
            value.get('default_enabled') is not False or
            value.get('format')!='single_elimination_16_teams' or
            type(value.get('rounds')) is not int or value['rounds']!=4 or
            type(value.get('match_minutes')) is not int or value['match_minutes']!=6 or
            value.get('rewards_mode')!='reference_only_disabled' or
            type(value.get('cups')) is not list or len(value['cups']) != count):
        raise ValueError('Unsupported tournament catalog/format/reward admission')
    result = {}
    ids = set()
    metadata = set()
    expected_fields=set(Cup.__dataclass_fields__)-{'historical_prize_json'}|{'historical_prize_reference'}
    if not extended:
        expected_fields -= {'minimum_brazilian_starters', 'minimum_five_star_skillers'}
    for row in value['cups']:
        if type(row) is not dict or set(row) != expected_fields:
            raise ValueError('Invalid tournament fields')
        if (type(row['key']) is not str or not row['key'] or row['key'] in result or
                type(row['name']) is not str or not 1<=len(row['name'])<=80 or
                type(row['service_id']) is not int or not 201 <= row['service_id'] < 201 + count or row['service_id'] in ids or
                type(row['metadata_service_id']) is not int or not 8203100 <= row['metadata_service_id'] < 8203100 + count or
                row['metadata_service_id'] in metadata or
                type(row['difficulty']) is not int or not 0<=row['difficulty']<=6 or
                row['required_quality'] not in (None,'bronze','silver','gold') or
                row['quality_scope']!='starting11_and_substitutes' or
                type(row['minimum_chemistry']) is not int or not 0<=row['minimum_chemistry']<=100 or
                type(row['unlock_trophies']) is not int or row['unlock_trophies']!=0):
            raise ValueError('Invalid tournament identity/requirement/art')
        if extended:
            art = re.fullmatch(r'trophy_(1103|1109|1111|1112|1153)_(bronze|silver|gold)', row['trophy_asset'])
            if art is None or row['trophy_silhouette'] != f'trophy_{art.group(1)}_dark':
                raise ValueError('Unsupported original trophy assignment')
            for field, maximum in (('minimum_brazilian_starters', 11), ('minimum_five_star_skillers', 11)):
                if type(row[field]) is not int or not 0 <= row[field] <= maximum:
                    raise ValueError('Invalid starter requirement')
        elif (
            row['trophy_asset'] not in ('trophy_1103_bronze','trophy_1103_silver','trophy_1103_gold')
            or row['trophy_silhouette'] != 'trophy_1103_dark'
        ):
            raise ValueError('Invalid original trophy assignment')
        prize=row['historical_prize_reference']
        if (type(prize) is not dict or set(prize)!={'coins','pack'} or
                type(prize['coins']) is not int or not 0<=prize['coins']<=1000000 or
                type(prize['pack']) is not str or not prize['pack']):
            raise ValueError('Invalid historical prize reference')
        fields = dict(row)
        fields['historical_prize_json'] = json.dumps(fields.pop('historical_prize_reference'), sort_keys=True)
        result[row['key']] = Cup(**fields)
        ids.add(row['service_id'])
        metadata.add(row['metadata_service_id'])
    return result


def quality(item):
    from .card_pool import card_index
    from .reconstructed_specials import validate_reference,version
    validate_reference(item)
    if item.special_version_id:return version(item.special_version_id).pack_eligibility['base_quality']
    return card_index()[item.resource_id].quality


def eligibility(cup,football,*,quality_for=quality,starter_facts=None):
    if type(cup) is not Cup:raise ValueError('Validated tournament required')
    owned={p.instance_id:p for p in football.owned_items};lineup={s.index:s.instance_id for s in football.active_lineup}
    failures=[]
    if any(i not in lineup or lineup[i] not in owned for i in range(11)):
        failures.append('incomplete_starting11')
    if cup.required_quality:
        if any(i not in lineup or lineup[i] not in owned for i in range(18)):
            failures.append('incomplete_starting11_and_substitutes')
        else:
            try:
                if any(quality_for(owned[lineup[i]])!=cup.required_quality for i in range(18)):
                    failures.append('player_quality_requirement')
            except (ValueError,KeyError):failures.append('unsupported_player_reference')
    if cup.minimum_chemistry:
        if football.squad_summary is None:failures.append('missing_stock_chemistry')
        elif football.squad_summary.chemistry<cup.minimum_chemistry:failures.append('minimum_chemistry')
    if cup.minimum_brazilian_starters or cup.minimum_five_star_skillers:
        from .tournament_starter_facts import facts
        from .card_pool import card_index
        supplied = facts() if starter_facts is None else starter_facts
        players = []
        for index in range(11):
            item = owned.get(lineup.get(index))
            card = card_index().get(item.resource_id) if item else None
            fact = supplied.get(card.player_id) if card and card.lookup_supported else None
            if fact is None:
                failures.append('unsupported_starter_facts')
                break
            players.append(fact)
        if len(players) == 11:
            if sum(nation == 54 for nation, skill_code in players) < cup.minimum_brazilian_starters:
                failures.append('minimum_brazilian_starters')
            if sum(skill_code == 4 for nation, skill_code in players) < cup.minimum_five_star_skillers:
                failures.append('minimum_five_star_skillers')
    return dict(eligible=not failures,failures=failures)


def draw_clubs(cup,run_identity):
    """Fifteen real supplied opponents; initial order only, no match results."""
    if type(cup) is not Cup or type(run_identity) is not str or not run_identity:
        raise ValueError('Pinned tournament and run identity required')
    pool=eligible_team_ids()
    if len(pool)<15:raise ValueError('Insufficient supplied tournament opponents')
    return tuple(sorted(pool,key=lambda tid:hashlib.sha256(f'{cup.key}:{run_identity}:{tid}'.encode()).digest())[:15])
