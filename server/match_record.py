"""User Bio record: wins/draws/losses and the last five results ("form").

Plate parser 00325044 (names decoded read-only from the live process, run 1524):
``Record`` -> 0034e3e4 {``DrawCount``, ``LossCount``, ``WinCount``} and the string
``LastFive``: '-'-separated tokens, each localized as LTXT_CMN_<token> by 00b52490
(W/D/L exist in eng_us; 1524 showed '*LTXT_CMN_WLWLW' for an unseparated string). The parser rewinds before
each member lookup, so member order does not matter.

Sources (no new state): committed Seasons matches in native-seasons.json (forfeits
are stored as losses) and tournament matches recorded by the accomplishments hook
(since it was enabled). ``after_season`` (count of Seasons matches when the
tournament match committed) interleaves the two; older entries without it use the
selector's seasons baseline, which precedes them.
"""
import json
from pathlib import Path


def results(account):
    """Chronological 'W'/'D'/'L' list, or None when the account has no match stores."""
    account = Path(account)
    seasons_path = account / 'native-seasons.json'
    if not seasons_path.exists():
        return None
    events = []
    matches = json.loads(seasons_path.read_bytes())['matches']
    for index, match in enumerate(matches):
        if match.get('status') == 'committed' and match.get('result') in ('W', 'D', 'L'):
            events.append(((index, 1, 0), match['result']))
    state_path = account / 'accomplishments.json'
    if state_path.exists():
        state = json.loads(state_path.read_bytes())
        for order, match in enumerate(state.get('matches', [])):
            if match.get('result') in ('W', 'D', 'L'):
                position = match.get('after_season', state.get('seasons_baseline', len(matches)))
                events.append(((position, 0, order), match['result']))
    return [result for _, result in sorted(events)]


def record(account):
    values = results(account)
    if not values:
        return None
    return {'wins': values.count('W'), 'draws': values.count('D'), 'losses': values.count('L'),
            'last_five': '-'.join(values[-5:])}


def plate_members(account):
    value = record(account)
    if value is None:
        return ''
    return ('<LastFive>%s</LastFive><Record><DrawCount>%d</DrawCount><LossCount>%d</LossCount>'
            '<WinCount>%d</WinCount></Record>'
            % (value['last_five'], value['draws'], value['losses'], value['wins']))
