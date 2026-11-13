"""Played-match DTOs captured271; experimental source-bound reward transport.

The aggregate validator is shared with Sim, but routes, clock response and
source provenance remain distinct. Never constructs a score or opaque save.
"""
from . import native_simulation_protocol as shared
from .offline_create_match import PATH as CREATE_PATH, validate_response
from .destroy_match import PATH as END_PATH

VERSION='native_played_match_v1'

def validate_source(source):
    if 'played_match' not in source:return
    marker=source['played_match']
    if type(marker) is not dict or set(marker)!={'version','create_response'} or marker['version']!=VERSION:
        raise ValueError('Invalid played match source marker')
    validate_response(marker['create_response'])
    if not source.get('atomic_match') or not source.get('native_xp_start'):
        raise ValueError('Played rewards require atomic native XP source')

def protocol(source):
    validate_source(source)
    if 'played_match' in source:
        import sys
        return sys.modules[__name__]
    return shared

def inspect_create(method,target,headers,body,season,football):
    if target!=CREATE_PATH:raise ValueError('Wrong played Create route')
    from .offline_create_match import response_for
    if response_for(method,target,headers,body,'clock',season,football_store=football) is None:
        raise ValueError('Unsupported original played Create')
    value=shared.inspect_create(method,shared.CREATE_PATH,headers,body,season,football)
    value['classification']='captured_native_played_create_only'
    return value

def play_ack(method,target,headers,body,football,*,enabled=False):
    if enabled is not True or target!=CREATE_PATH:return None
    from .play_game import response_for
    return response_for(method,target,headers,body,football)

def inspect_end(method,target,headers,body,season,football):
    if target!=END_PATH:raise ValueError('Wrong played End route')
    value=shared.inspect_end(method,shared.END_PATH,headers,body,season,football)
    value['classification']='native_played_result_aggregate_proposal_only'
    return value

def report_start_time(source):
    validate_source(source)
    return str(source["played_match"]["create_response"]["startDateTime"]) if "played_match" in source else "-1"
