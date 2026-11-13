"""Captured739 Free Gold ApplyCard, opt-in and exact-account scoped."""
from pathlib import Path
from .identity import json_response
from .native_free_coins_protocol import decode

COORDINATOR = None


def configure(coordinator=None):
    global COORDINATOR
    COORDINATOR = coordinator


def selected(football_state):
    return COORDINATOR if COORDINATOR is not None and football_state and Path(football_state).resolve() == COORDINATOR.football.path else None


def recover(football_state):
    c = selected(football_state)
    if c:c.recover()


def response_for(method,target,headers,body,football_state):
    c = selected(football_state)
    if c is None:return None
    try:c.preview(decode(method,target,headers,body))
    except (ValueError,TypeError,KeyError,UnicodeError):return None
    return json_response({'itemData':[]})


def commit_request(method,target,headers,body,football_state):
    c = selected(football_state)
    if c is None:return None
    try:
        source=decode(method,target,headers,body)
        c.preview(source)
    except (ValueError,TypeError,KeyError,UnicodeError):return None
    c.redeem(source)
    return json_response({'itemData':[]})
