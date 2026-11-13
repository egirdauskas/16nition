"""Isolated captured533 empty ApplyCard. Positive stock effect remains opt-in."""
import json
import re
from pathlib import Path
from .game_auth import SID
from .identity import json_response
from .apply_card import PREFIX

COORDINATOR = None

def configure(coordinator=None):
    global COORDINATOR
    COORDINATOR = coordinator

def selected(football_state):
    return COORDINATOR if COORDINATOR is not None and football_state and Path(football_state).resolve()==COORDINATOR.football.path else None

def recover(football_state):
    coordinator = selected(football_state)
    if coordinator: coordinator.recover()

def decode(method, target, headers, body):
    if (method != 'POST' or headers.get(b'host') != b'10.0.2.2:18081' or
        headers.get(b'x-ut-sid') != SID.encode() or headers.get(b'content-type') != b'application/json' or
        headers.get(b'content-length') != str(len(body)).encode() or
        not re.fullmatch(re.escape(PREFIX)+r'[1-9][0-9]*', target)):
        raise ValueError('Not captured authenticated FreeCoins ApplyCard')
    # Only this exact empty-target operation. GK/manager ApplyCard stays separate.
    if json.loads(body) != {'apply':[]}:
        raise ValueError('Unmapped FreeCoins ApplyCard body')
    return int(target[len(PREFIX):])

def response_for(method, target, headers, body, football_state):
    coordinator = selected(football_state)
    if coordinator is None: return None
    try:
        source = decode(method, target, headers, body)
        coordinator.preview(source)
    except (ValueError,TypeError,KeyError,UnicodeError): return None
    return json_response({'itemData':[]})

def commit_request(method, target, headers, body, football_state):
    coordinator = selected(football_state)
    if coordinator is None: return None
    try: source = decode(method, target, headers, body)
    except (ValueError,TypeError,KeyError,UnicodeError): return None
    coordinator.redeem(source)
    return json_response({'itemData':[]})
