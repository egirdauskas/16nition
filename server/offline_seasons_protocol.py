"""Observed offline RS4 adapters over local rules and native-generated progress."""
import base64,json,struct
from .game_auth import SID
from .identity import json_response
from .offline_season_list import PATH as LIST_PATH
from .offline_current_season import PATH as CURRENT_PATH
from .local_seasons import CurrentSeason
from .season_blob import decode_envelope,validated_progress

def definition_response(definition):
    definition.validate()
    result={'seasons':[{'id':definition.season_id,'type':'OFFLINE',
        'divisionId':11-definition.division_index,'numMatches':len(definition.fixtures),
        'matchLengthMin':definition.match_minutes,'untilStartSeconds':0,
        'untilEndSeconds':2147483647,'elgOperation':'AND','elgReq':[],
        'prizeSet':[{'prizeLevel':level,'thresholdPoint':0,'awardMappings':[]}
            for level in ['RELEGATION','MAINTENANCE','PROMOTION','CHAMPIONSHIP']],
        'matches':[{'teamId':f.team_id,'difficulty':f.difficulty,'roundId':f.round_number,
                    'rewardMult':0,'coins':0} for f in definition.fixtures]}]}
    from .season_choices import ChoiceDefinition,load_catalog
    if isinstance(definition,ChoiceDefinition):
        from .season_choice_preview import eligibility,identities
        row=result['seasons'][0]
        row['elgReq']=eligibility(load_catalog()[definition.competition_key])
        row['trophyResourceId']=identities()[definition.competition_key][1]
    return result

def current_response(store):
    current=store.load()
    if current is None:return {'seasonId':-1}
    raw=bytes.fromhex(current.client_state_hex)
    wire=bytes.fromhex(current.client_state_envelope_hex) if current.client_state_envelope_hex is not None else struct.pack('<I',len(raw))+raw
    return {'seasonId':current.season_id,'round':current.round_number,
            'userPoints':current.user_points,
            'data':base64.b64encode(wire).decode('ascii')}

def parse_season_save(body,store):
    value=json.loads(body)
    if type(value) is not dict or set(value)!={'round','data'} or type(value['round']) is not int or not 1 <= value['round'] <= len(store.definition.fixtures) + 1 or type(value['data']) is not str:raise ValueError('Unsupported season save')
    wire=base64.b64decode(value['data'],validate=True)
    if base64.b64encode(wire).decode('ascii')!=value['data']:raise ValueError('Noncanonical native Base64')
    raw=decode_envelope(wire)
    points=validated_progress(raw,value['round'])
    current=CurrentSeason(store.definition.season_id,store.definition.division_index,value['round'],points,raw.hex(),wire.hex() if value['round']>1 else None)
    old=store.load()
    if old!=current and not ((old is None and current.round_number==1) or (old is not None and current.round_number==old.round_number+1)):
        raise ValueError('Unsupported season transition/retry')
    return current

def response_for(method,target,headers,body,store,policy=None):
    if headers.get(b'host')!=b'10.0.2.2:18081' or headers.get(b'x-ut-sid')!=SID.encode():return None
    if method=='GET' and not body and headers.get(b'content-length',b'0')==b'0':
        list_path=f'/ut/game/fifaworldmobile/season/list?active=true&count=99&divisionList={11-store.definition.division_index}&type=offline'
        if target==list_path:
            if policy is not None:
                from .season_revival_policy import definition_with_policy
                return json_response(definition_with_policy(store.definition,policy))
            return json_response(definition_response(store.definition))
        if target==CURRENT_PATH:return json_response(current_response(store))
    expected=f'/ut/game/fifaworldmobile/season/{store.definition.season_id}/division/{11-store.definition.division_index}/user'
    if method=='PUT' and target==expected and headers.get(b'content-length')==str(len(body)).encode():
        parse_season_save(body,store).validate(store.definition)
        # Common response parser01054e60 ignores payload and returns1.
        return json_response({})
    return None

def commit_request(method,target,headers,body,store):
    # Called only after hold/close controls permit sending the acknowledgment.
    # Persist before send; retries are idempotent if the connection fails.
    if method=='PUT' and response_for(method,target,headers,body,store):
        return store.save(parse_season_save(body,store))
    return None
