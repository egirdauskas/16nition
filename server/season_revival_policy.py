"""Authorized custom offline thresholds; no historical numeric claims or grants.

Pure evaluation only. A final outcome is a proposal until an observed stock
completion/promotion contract can commit it. Opaque SeasonStore bytes stay owned
by the existing adapter; this module neither creates nor rewrites them.
"""
from dataclasses import dataclass
import json
from pathlib import Path
from .season_progression import validate_progress

POLICY = Path(__file__).parent / 'policy/offline-seasons-revival.json'
LEVELS = ('RELEGATION', 'MAINTENANCE', 'PROMOTION', 'CHAMPIONSHIP')


@dataclass(frozen=True)
class DivisionPolicy:
    division: int
    maintenance: int
    promotion: int | None
    championship: int
    coins: tuple
    reference_pack_labels: tuple = ((), (), (), ())

    def validate(self):
        if any(type(v) is not int for v in (self.division, self.maintenance, self.championship)):
            raise ValueError('Integer policy values required')
        if not 1 <= self.division <= 10 or not 0 <= self.maintenance < self.championship <= 30:
            raise ValueError('Unattainable or unordered thresholds')
        if self.maintenance == 0 and self.division != 10:
            raise ValueError('Only bottom division can hold at zero points')
        if self.promotion is None:
            if self.division != 1: raise ValueError('Only top division disables promotion')
        elif type(self.promotion) is not int or not self.maintenance < self.promotion < self.championship:
            raise ValueError('Invalid promotion threshold')
        if len(self.coins) != 4:
            raise ValueError('Invalid proposed rewards')
        for index, value in enumerate(self.coins):
            if value is None:
                if not ((index == 0 and self.division == 10 and self.maintenance == 0) or (index == 2 and self.division == 1 and self.promotion is None)):
                    raise ValueError('Reward missing for an available outcome')
            elif type(value) is not int or not 0 <= value <= 100000:
                raise ValueError('Invalid proposed rewards')
        # Console pack bonuses can make title cash lower than promotion cash.
        # Keep source cash components intact; bonus labels never grant packs.
        if len(self.reference_pack_labels) != 4 or any(type(labels) is not tuple or any(
                label not in ('BP', 'PBP', 'SP', 'PSP', 'JSP', 'JPSP', 'GP', 'JGP') for label in labels)
                for labels in self.reference_pack_labels):
            raise ValueError('Invalid reference-only bonus pack labels')
        return self

    def threshold_blocks(self):
        # Four fully initialized blocks; positive preview/grant not certified.
        self.validate()
        # Top division has no promotion. Initialize its unused wire block to0;
        # the recovered stock getter disables promotion for Division1 itself.
        return [{'prizeLevel': level, 'thresholdPoint': threshold, 'awardMappings': []}
                for level, threshold in zip(LEVELS, (0, self.maintenance, self.promotion or 0, self.championship))]

    def evaluate(self, played, points):
        self.validate()
        validate_progress(played,points)
        band = ('CHAMPIONSHIP' if points >= self.championship else
                'PROMOTION' if self.promotion is not None and points >= self.promotion else
                'MAINTENANCE' if points >= self.maintenance else 'RELEGATION')
        complete = played == 10
        outcome = 'in_progress'
        target = self.division
        if complete:
            if band == 'CHAMPIONSHIP': outcome = 'championship'
            elif band == 'PROMOTION': outcome = 'promotion' if self.division > 1 else 'retention'
            elif band == 'MAINTENANCE': outcome = 'retention'
            else: outcome = 'floor_retention' if self.division == 10 else 'relegation'
            if band in ('CHAMPIONSHIP', 'PROMOTION') and self.division > 1: target -= 1
            elif band == 'RELEGATION' and self.division < 10: target += 1
        return {'classification': 'revival_policy', 'division': self.division,
                'matches_played': played, 'points': points, 'games_remaining': 10 - played,
                'preview_band': band, 'title_notice_eligible': points >= self.championship,
                'complete': complete, 'outcome': outcome, 'proposed_next_division': target,
                'proposed_season_coins': self.coins[LEVELS.index(band)] if complete else 0,
                'reference_bonus_pack_labels': list(self.reference_pack_labels[LEVELS.index(band)]) if complete else [],
                'pack_grants_enabled': False,
                'grants_enabled': False, 'promotion_commit_enabled': False,
                'maximum_final_points': points + 3 * (10 - played)}


@dataclass(frozen=True)
class RevivalSeasonPolicy:
    version: str
    divisions: tuple

    def for_division(self, division):
        if type(division) is not int: raise ValueError('Invalid division')
        for item in self.divisions:
            if item.division == division: return item
        raise ValueError('Division not configured')

    def evaluate_current(self, current):
        return self.for_division(current.division_index).evaluate(current.round_number - 1, current.user_points)


def load_policy(path=POLICY):
    value = json.loads(Path(path).read_text())
    versions = ('offline_seasons_v1', 'offline_seasons_console_fifa16_v2')
    console = value.get('version') == versions[1]
    expected = {'classification', 'version', 'matches_per_season', 'grants_enabled', 'promotion_commit_enabled', 'divisions', 'rationale'}
    if console: expected.add('reference')
    if set(value) != expected:
        raise ValueError('Unexpected revival policy fields')
    if (value['classification'] != 'revival_policy' or value['version'] not in versions
            or type(value['matches_per_season']) is not int or value['matches_per_season'] != 10
            or value['grants_enabled'] is not False or value['promotion_commit_enabled'] is not False):
        raise ValueError('Unsupported policy or unproven grant/transition activation')
    if console:
        reference = value['reference']
        if (type(reference) is not dict or reference.get('source_classification') != 'third_party_period_console_table'
                or reference.get('historical_mobile_values_recovered') is not False
                or reference.get('adoption') != 'explicit_user_authorized_revival_policy'):
            raise ValueError('Console adoption must retain non-Mobile provenance')
    items = []
    for division, row in sorted(value['divisions'].items(), key=lambda r: int(r[0])):
        fields = {'maintenance', 'promotion', 'championship', 'proposed_coins'}
        if console: fields.add('reference_pack_labels')
        if str(int(division)) != division or set(row) != fields:
            raise ValueError('Invalid division configuration')
        if set(row['proposed_coins']) != set(LEVELS): raise ValueError('Missing reward band')
        if console and set(row['reference_pack_labels']) != set(LEVELS): raise ValueError('Missing reference pack band')
        packs = tuple(tuple(row['reference_pack_labels'][k]) for k in LEVELS) if console else ((), (), (), ())
        items.append(DivisionPolicy(int(division), row['maintenance'], row['promotion'], row['championship'],
                                   tuple(row['proposed_coins'][k] for k in LEVELS), packs).validate())
    if {p.division for p in items} != set(range(1, 11)): raise ValueError('Ten explicit divisions required')
    return RevivalSeasonPolicy(value['version'], tuple(items))


def definition_with_policy(definition, policy):
    """Thin opt-in SeasonList projection of already-mapped threshold fields.

    No service flag/default is changed. Native completion/division rollover and
    positive prize vectors remain disabled pending genuine stock evidence.
    """
    from .offline_seasons_protocol import definition_response
    value = definition_response(definition)
    value['seasons'][0]['prizeSet'] = policy.for_division(definition.division_index).threshold_blocks()
    return value
