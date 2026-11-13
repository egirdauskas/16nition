"""Compact immutable competition references for prospective match sources.

Legacy sources retain their original definition reconstruction. New references
identify supplied policy, never copy assets or infer a next competition.
"""
import json
from dataclasses import asdict, replace
from hashlib import sha256

VERSION = 'native_match_competition_reference_v1'


def snapshot(value):
    from .season_choices import ChoiceDefinition
    if not isinstance(value, ChoiceDefinition): return None
    value.validate()
    from .native_season_completion import encode
    return {'version': VERSION, 'competition_key': value.competition_key,
            'fixture_seed': value.fixture_seed, 'season_id': value.season_id,
            'catalog_sha256': value.catalog_sha256,
            'definition_sha256': sha256(encode(asdict(value))).hexdigest()}


def resolve(current, source, history=None):
    marker = source['atomic_match']
    saved = json.loads(bytes.fromhex(marker['season_before_hex']))['current']
    ref = marker.get('competition_reference')
    if 'competition_reference' not in marker:
        if history and source['cycle_id'] in history:
            from .local_seasons import definition_from_data
            value=definition_from_data(history[source['cycle_id']])
            if (value.division_index,value.season_id)!=(saved['division_index'],saved['season_id']):
                raise ValueError('Archived cycle definition identity differs')
            return value
        return replace(current, division_index=saved['division_index'], season_id=saved['season_id'])
    keys = {'version','competition_key','fixture_seed','season_id','catalog_sha256','definition_sha256'}
    if type(ref) is not dict or set(ref) != keys or ref['version'] != VERSION:
        raise ValueError('Invalid pinned competition reference')
    from .season_choices import definition, load_catalog
    catalog = load_catalog()
    if (type(ref['competition_key']) is not str or ref['competition_key'] not in catalog
            or type(ref['season_id']) is not int or ref['season_id'] != saved['season_id']):
        raise ValueError('Pinned competition identity differs')
    value = definition(catalog[ref['competition_key']], ref['season_id'], ref['fixture_seed'])
    value.validate()
    if value.division_index != saved['division_index'] or snapshot(value) != ref:
        raise ValueError('Pinned competition definition differs')
    return value


def archive_unreferenced(current, state):
    """Freeze the existing reconstruction once per old cycle, not per match."""
    history=dict(state.get('season_definition_history',{}))
    for source in state['matches']+state.get('aborted_matches',[]):
        if source.get('atomic_match') and 'competition_reference' not in source['atomic_match']:
            value=json.loads(json.dumps(asdict(resolve(current,source,history))))
            if source['cycle_id'] in history and history[source['cycle_id']]!=value:
                raise ValueError('Cannot rewrite archived cycle definition')
            history[source['cycle_id']]=value
    return history


def validate_history(state):
    history=state.get('season_definition_history',{})
    if type(history) is not dict:raise ValueError('Invalid cycle definition archive')
    from .local_seasons import definition_from_data
    for cycle,value in history.items():
        sources=[s for s in state['matches']+state.get('aborted_matches',[]) if s['cycle_id']==cycle and s.get('atomic_match')]
        if not sources:raise ValueError('Cycle definition has no original source')
        definition=definition_from_data(value)
        for source in sources:resolve(definition,source,history)
