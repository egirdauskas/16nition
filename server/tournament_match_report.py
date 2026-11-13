"""Reuse the observed OfflineMatchInfo/GameReport contract for tournament sources."""

import hashlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

from .account_transaction import account_locked, atomic
from .local_profile import load_profile
from .native_match_session import (
    NS, TARGET, PLAYED_TARGET, REPORT_PATH, inspect_report, session_id,
)
from .native_match_xp import response as xp_response
from .tournament_reward_policy import quote
from .victory_session import xml_response


def identity(source):
    key = uuid.uuid5(uuid.NAMESPACE_URL, 'tournament-match:' + source['quote']['source_id'])
    return session_id(str(key))


def validate_auth(account, headers):
    profile = load_profile(Path(account) / 'profile.json')
    return (
        headers.get(b'host') == b'10.0.2.2:18081'
        and headers.get(b'securitytoken') == profile.victory_security_token.encode()
        and headers.get(b'userid') == profile.user_id.encode()
    )


@account_locked
def response_for(method, target, headers, body, account, *, commit=False):
    from .native_tournament_match import LEDGER, ledger
    from .goal_event import PATH as GOAL_PATH, response_for as goal_reply

    if target not in (TARGET, PLAYED_TARGET, REPORT_PATH, GOAL_PATH) or not validate_auth(account, headers):
        return None
    value = ledger(account)
    source = value.get('active')
    if method == 'POST' and target == REPORT_PATH:
        # Retain only the latest checkpoint and per-cup closure responses.
        # This serves exact late callbacks without an ever-growing match log.
        previous = [value.get('last', {}), *value.get('closed', {}).values()]
        for record in previous:
            report = record.get('reward_receipt', {}).get('report')
            if report and report['body_hex'] == body.hex():
                return xml_response(report['response_xml'])
    if not source or source.get('reward_start') is None:
        return None
    if method == 'POST' and target == GOAL_PATH:
        return goal_reply(method, target, headers, body, match_session_id=identity(source))
    played = source['quote'].get('kind') == 'played'
    if method == 'GET' and target == (PLAYED_TARGET if played else TARGET) and not body:
        return xml_response(
            f'<OfflineMatchInfo xmlns="{NS}"><MatchSessionId>{identity(source)}</MatchSessionId></OfflineMatchInfo>'
        )
    if method != 'POST' or target != REPORT_PATH or source['phase'] not in ('playing', 'ended'):
        return None
    stored = source.get('xp_report')
    if stored:
        return xml_response(stored['response_xml']) if stored['body_hex'] == body.hex() else None
    start_time = str(source['create_response']['startDateTime']) if played else '-1'
    observed = inspect_report(
        method, target, headers, body, SimpleNamespace(account=Path(account)),
        expected_session=identity(source), expected_start_time=start_time,
    )
    # 1387: a knockout level after extra time reports MatchDraw (0-0, then
    # penalties). Stage it like W/L; the DRAW End stays held until captured.
    if observed is None:
        return None
    calculation = quote(source['reward_start'], observed['result'])['match']
    response = xp_response(calculation, source.get('level_reward_start'))
    if commit:
        source['xp_report'] = {
            'body_hex': body.hex(),
            'sha256': hashlib.sha256(body).hexdigest(),
            'observation': observed,
            'response_xml': response,
        }
        atomic(Path(account) / LEDGER, (json.dumps(value, indent=2, sort_keys=True) + '\n').encode())
    return xml_response(response)
