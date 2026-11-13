"""User Bio favourites: pure SaveFavorites preview and explicit commit."""
from dataclasses import replace
from functools import lru_cache
import xml.etree.ElementTree as ET

PATH = '/victory_fwm_s2/Engine.svc/User/Persona/SaveFavorites'
NS = 'http://schemas.datacontract.org/2004/07/Victory.FW.Components.AccountFeature.TransferObjects'
ACK = b'<Response xmlns="http://schemas.datacontract.org/2004/07/Victory.Service"/>'
FIELDS = ('FavoriteCountryId', 'FavoritePlayerId', 'FavoriteTeamId')


@lru_cache(maxsize=1)
def _supplied_ids():
    from .season_content import ROOT, FootballDB, eligible_team_ids
    eligible_team_ids()
    db = ROOT / 'native/content/main.13.com.ea.gp.fifaworld/data/db/fifa_ng_db.db'
    source = FootballDB(db, db.with_name('fifa_ng_db-meta.xml'))
    nations = frozenset(row['nationid'] for row in source.rows('nations', ['nationid']))
    players = frozenset(row['playerid'] for row in source.rows('players', ['playerid']))
    return nations, players


def valid_country(value):
    return value is None or (type(value) is int and value in _supplied_ids()[0])


def valid_player(value):
    return value is None or (type(value) is int and value in _supplied_ids()[1])


def parse(body):
    """Exact captured shape -> (country, player, team), with 0 mapped to None."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    expected = ['{%s}%s' % (NS, field) for field in FIELDS]
    if root.tag != '{%s}Favorites' % NS or [child.tag for child in root] != expected:
        return None
    values = []
    for child in root:
        text = child.text or ''
        if len(child) or not text.isdigit() or len(text) > 9:
            return None
        values.append(int(text) or None)
    return tuple(values)


def plate_xml(profile):
    values = (profile.favorite_country_id, profile.favorite_player_id,
              profile.favorite_team_id)
    members = ''.join('<%s>%d</%s>' % (name, value, name)
                      for name, value in zip(FIELDS, values) if value is not None)
    return '<FavoriteCountryTeamPlayer>%s</FavoriteCountryTeamPlayer>' % members if members else ''


def _validated_request(method, target, headers, body, store=None):
    if method != 'POST' or target != PATH or headers.get(b'host') != b'10.0.2.2:18081':
        return None
    if headers.get(b'content-type', b'').split(b';', 1)[0] != b'text/xml' or len(body) > 4096:
        return None
    if store is None:
        from .local_profile import ProfileStore
        store = ProfileStore()
    profile = store.load()
    if (headers.get(b'securitytoken') != profile.victory_security_token.encode()
            or headers.get(b'userid') != profile.user_id.encode()):
        return None
    values = parse(body)
    if values is None:
        return None
    country, player, team = values
    from .season_content import eligible_team_ids
    if (not valid_country(country) or not valid_player(player)
            or (team is not None and team not in eligible_team_ids())):
        return None
    return store, values


def _ack():
    from .victory_session import xml_response
    return xml_response(ACK)


def response_for(method, target, headers, body):
    """Validate the captured operation and preview its exact ACK without writes."""
    if _validated_request(method, target, headers, body) is None:
        return None
    return _ack()


def commit_request(method, target, headers, body):
    """Persist validated favourites once, preserving all unrelated profile data."""
    validated = _validated_request(method, target, headers, body)
    if validated is None:
        return None
    store, (country, player, team) = validated
    from .first_run_account import pending_session, save_preferences
    account = store.path.parent
    if pending_session(account) is not None:
        save_preferences(account, {
            'favorite_country_id': country,
            'favorite_player_id': player,
            'favorite_team_id': team,
        })
        return _ack()
    with store.transaction():
        current = store.load()
        updated = replace(current, favorite_country_id=country,
                          favorite_player_id=player, favorite_team_id=team)
        if updated != current:
            store.save(updated)
    return _ack()
