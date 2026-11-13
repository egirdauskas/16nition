"""Opt-in response for the exact captured offline SeasonList operation.

Parser010399b4 recognizes seasons[]. Run155 proves the empty vector invokes the
frontend success path and dispatches SeasonLoadData. The default supplies no
definition/progress. Two explicit diagnostic records are guarded below; the
durable ten-fixture adapter is separate. Existing solved responses stay fixed.
"""
import json
from pathlib import Path
from .game_auth import SID
from .identity import json_response
PATH='/ut/game/fifaworldmobile/season/list?active=true&count=99&divisionList=11&type=offline'
# Bounded definition-source probe, not a playable competition. Explicit byte /
# prize defaults avoid the uninitialized nested-field hazards of a bare record.
DEFINITION_PROBE={'id':1,'type':'OFFLINE','divisionId':11,'numMatches':0,
    'untilStartSeconds':0,'untilEndSeconds':2147483647,
    'elgOperation':'AND','elgReq':[],'matches':[],
    'prizeSet':[{'prizeLevel':level,'thresholdPoint':0,'awardMappings':[]}
                for level in ['RELEGATION','MAINTENANCE','PROMOTION','CHAMPIONSHIP']]}
# Locally authored one-fixture rules, not historical EA season progress.
# GetOfflineSeasonOpponents02191c30 resolves teamId via the supplied teams DB.
ONE_FIXTURE={**DEFINITION_PROBE,'numMatches':1,'matchLengthMin':6,
    'matches':[{'teamId':1,'difficulty':0,'roundId':1,'rewardMult':0,'coins':0}]}
def validate_response(value):
    if type(value) is not dict or set(value)!={'seasons'} or type(value['seasons']) is not list:
        raise ValueError('Expected exact seasons array envelope')
    canonical=json.dumps(value,sort_keys=True,separators=(',',':'))
    allowed=[{'seasons':[]},{'seasons':[DEFINITION_PROBE]},{'seasons':[ONE_FIXTURE]}]
    if canonical not in [json.dumps(x,sort_keys=True,separators=(',',':')) for x in allowed]:
        raise ValueError('Unsupported diagnostic offline season response')
    return value

def response_for(method,target,headers,body,candidate):
    if (method!='GET' or target!=PATH or body or headers.get(b'host')!=b'10.0.2.2:18081'
        or headers.get(b'x-ut-sid')!=SID.encode() or headers.get(b'content-length',b'0')!=b'0'):
        return None
    value=validate_response(json.loads(Path(candidate).read_text()))
    return json_response(value)
