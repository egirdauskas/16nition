"""Scoped zero-reward DestroyMatch completion candidate; no domain writes.

Factory0105700c/parser01057c04/consumer01049e90 support constructor defaults.
Request result/item proposals are checked for the observed local ownership
shape, then left untouched. This does not persist results or item changes.
"""
import json
from .game_auth import SID
from .identity import json_response
from .match_roster import match_players

PATH = '/ut/game/fifaworldmobile/match/end'

def response_for(method, target, headers, body, football_store):
    if (method != 'PUT' or target != PATH
            or headers.get(b'host') != b'10.0.2.2:18081'
            or headers.get(b'x-ut-sid') != SID.encode()
            or headers.get(b'content-type') != b'application/json'):
        return None
    try:
        if b'content-length' in headers and int(headers[b'content-length']) != len(body):
            return None
        value = json.loads(body)
        if type(value) is not dict or set(value) != {'endReason', 'matchDifficulty', 'myRating', 'opponentRating', 'items', 'myMatchStats', 'opponentMatchStats'}:
            return None
        if type(value['endReason']) is not str or not value['endReason']:
            return None
        if any(type(value[k]) is not int for k in ['matchDifficulty', 'myRating', 'opponentRating']):
            return None
        if any(type(value[k]) is not dict for k in ['myMatchStats', 'opponentMatchStats']):
            return None
        if type(value['items']) is not list:
            return None
        ids = []
        for item in value['items']:
            if type(item) is not dict or type(item.get('id')) is not int:
                return None
            ids.append(item['id'])
        state=football_store.load(1)
        owned = {item.instance_id for item in state.owned_items}
        participants = match_players(state)
        # Genuine363 reports slots0..17 (eleven plus seven substitutes),
        # excluding reserve slot18 and the manager. Keep an exact match
        # roster check; never accept an arbitrary owned subset or inventory.
        if state.active_lineup and not participants:return None
        expected=participants if state.active_lineup else owned
        if len(ids) != len(set(ids)) or set(ids) != expected or not set(ids)<=owned:
            return None
        return json_response({})
    except (ValueError, UnicodeError, TypeError):
        return None
