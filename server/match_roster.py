"""Stock match roster boundaries observed in363; account squad stays untouched.

Genuine12-item PlayGame includes starters+manager. Genuine18-player DestroyMatch
contains slots0..17; slot18 reserve and manager are excluded. No item grants,
resource/instance remapping or condition proposals are applied.
"""
STARTERS=11
MATCH_PLAYERS=18

def match_players(state):
    return {slot.instance_id for slot in state.active_lineup if slot.index<MATCH_PLAYERS}

def roster_roles(state):
    return {'starters':[slot.instance_id for slot in sorted(state.active_lineup,key=lambda s:s.index) if slot.index<STARTERS],
            'substitutes':[slot.instance_id for slot in sorted(state.active_lineup,key=lambda s:s.index) if STARTERS<=slot.index<MATCH_PLAYERS],
            'reserves':[slot.instance_id for slot in sorted(state.active_lineup,key=lambda s:s.index) if slot.index>=MATCH_PLAYERS],
            'manager':state.active_manager.instance_id if state.active_manager else None}
