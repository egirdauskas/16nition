"""A completed selected competition waits for a genuine next choice."""
KEY='pending_competition_selection'
VERSION='native_pending_competition_selection_v1'


def snapshot(source,history=None):
    import copy
    ref=source.get('atomic_match',{}).get('competition_reference')
    if ref is None:
        from .local_seasons import definition_from_data
        from .season_choice_reference import resolve
        from .native_season_completion import encode,digest
        if not history or source['cycle_id'] not in history:raise ValueError('Completed legacy competition needs its archived definition')
        value=definition_from_data(history[source['cycle_id']]);resolve(value,source,history)
        ref={'version':'native_legacy_choice_handoff_v1','cycle_id':source['cycle_id'],
             'definition_sha256':digest(encode(history[source['cycle_id']]))}
    return {'version':VERSION,'completed_source_id':source['id'],'definition_reference':copy.deepcopy(ref)}


def validate(state):
    from .season_forfeit import validate_pending
    if validate_pending(state):return
    marker=state['cycle'].get(KEY)
    if KEY not in state['cycle']:return
    if (type(marker) is not dict or state['active_match'] is not None
            or state['cycle']['status']!='awaiting_native_initialization'
            or state['cycle']['initial_native_anchor'] is not None
            or state['cycle'].get('season_choice_selection') is not None):
        raise ValueError('Invalid pending competition selection')
    source=next((s for s in state['matches'] if s['id']==marker.get('completed_source_id')),None)
    if (source is None or source.get('native_atomic_final') is not True
            or source['cycle_id']!=state['cycle'].get('previous_cycle_id')
            or marker!=snapshot(source,state.get('season_definition_history'))
            or not any(c['receipt_id']==source['id'] and c['next_cycle_id']==state['cycle']['id'] for c in state['completions'])):
        raise ValueError('Pending competition lost its committed predecessor')
