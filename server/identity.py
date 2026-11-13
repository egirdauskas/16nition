"""Only observed anonymous local identity transitions. No production requests."""
import json
import hashlib
from urllib.parse import urlsplit,parse_qs

def json_response(data):
    body=json.dumps(data,separators=(',',':')).encode()
    return b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body

def response_for(method,target,headers,body=b'',persona_id=None,fut_auth_code=False,victory_auth_code=False):
    url=urlsplit(target);query=parse_qs(url.query)
    if (method == 'GET' and not body and headers.get(b'host') == b'10.0.2.2:18081'
            and url.path == '/user/api/android/getDeviceID'
            and query.get('apiVer') == ['1.0.0'] and query.get('hwId') == ['2363']):
        android_ids = query.get('androidId', [])
        hashes = query.get('macHash', [])
        if (len(android_ids) != 1 or len(android_ids[0]) != 16
                or any(char not in '0123456789abcdef' for char in android_ids[0])
                or (hashes and (len(hashes) != 1 or len(hashes[0]) != 64
                               or any(char not in '0123456789abcdef' for char in hashes[0])))):
            return None
        android_id = android_ids[0]
        if android_id == '19fb0791bef293e2':
            # Preserve the original run303 identity and run304/305 cache-miss gate.
            device_id = 'bf00f7a037db3d162c782a4dc926236ace8c5cb12fb2397cf89f47837e4da4c9'
        else:
            # Run1566 is the same genuine Nimble request from a clean device.
            # Its mapped callback reads one deviceId string. This local opaque
            # namespace is stable across restarts and independent of club saves.
            device_id = hashlib.sha256(('ignition:synergy-device:v1:' + android_id).encode('ascii')).hexdigest()
        return json_response({'deviceId': device_id})
    if (method == 'GET' and not body and headers.get(b'host') == b'10.0.2.2:18081'
            and url.path == '/user/api/android/getAnonUid'
            and query.get('apiVer') == ['1.0.0'] and query.get('hwId') == ['2363']
            and query.get('updatePriority') == ['false']):
        device_ids = query.get('eadeviceid', [])
        if (len(device_ids) != 1 or len(device_ids[0]) != 64
                or any(char not in '0123456789abcdef' for char in device_ids[0])):
            return None
        device_id = device_ids[0]
        if device_id == 'bf00f7a037db3d162c782a4dc926236ace8c5cb12fb2397cf89f47837e4da4c9':
            anonymous_id = '2721906435752'
        else:
            digest = hashlib.sha256(('ignition:synergy-anonymous:v1:' + device_id).encode('ascii')).digest()
            anonymous_id = str(1000000000000 + int.from_bytes(digest[:8], 'big') % 9000000000000)
        # Run1567 captured this uncached path. SynergyEnvironmentUpdater.4 reads
        # uid.toString(), stores the String, then completes environment startup.
        return json_response({'uid': anonymous_id})
    if (method == 'GET' and not body and headers.get(b'host') == b'10.0.2.2:18081'
            and url.path == '/connect/upidtoken'
            and query.get('client_id') == ['FIFA-WORLD-MOBILE-CLIENT-ANDROID']):
        # Run1568: AuthenticatorAnonymous.getUpidToken reads the entire body as
        # an opaque String, persists UpidToken, then puts it in /connect/auth.
        token = b'fifa16-local-upid'
        return (b'HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\n'
                b'Connection: close\r\nContent-Length: ' + str(len(token)).encode()
                + b'\r\n\r\n' + token)
    if ((fut_auth_code or victory_auth_code) and method=='GET' and headers.get(b'host')==b'10.0.2.2:18081'
        and url.path=='/connect/auth'
        and ((fut_auth_code and query.get('client_id')==['FUT-SERVER'])
             or (victory_auth_code and query.get('client_id')==['FIFA-WORLD-MOBILE-SERVER-ANDROID']))
        and query.get('response_type')==['code']
        and query.get('access_token')==['fifa16-local-access']
        and query.get('redirect_uri')==['nucleus:rest']):
        # Run24 request; AuthenticatorBase.requestAuthCode consumes nonempty code.
        from server.native_pack_sessions import auth_code
        return json_response({'code':auth_code() if query['client_id']==['FUT-SERVER'] else 'fifa16-local-victory-code'})
    if (method=='GET' and headers.get(b'host')==b'10.0.2.2:18081'
        and url.path=='/connect/auth'
        and query.get('mobile_login_type')==['mobile_game_UPID']
        and query.get('response_type')==['code']
        and query.get('redirect_uri')==['nucleus:rest']
        and query.get('mobile_UPIDToken') and query.get('client_id')):
        # Run 16; AuthenticatorAnonymous consumes only a nonempty code string.
        return json_response({'code':'fifa16-local-auth-code'})
    if method=='POST' and headers.get(b'host')==b'10.0.2.2:18081' and url.path=='/connect/token':
        form=parse_qs(body.decode('ascii',errors='replace'))
        if (form.get('grant_type')==['authorization_code']
            and form.get('code')==['fifa16-local-auth-code']
            and form.get('client_secret')==['fifa16-local-lab']
            and form.get('redirect_uri')==['nucleus:rest']):
            # Run 17; token parser requires nonempty access/refresh strings and
            # both expiry fields. Opaque values have meaning only in this lab.
            return json_response({'access_token':'fifa16-local-access',
                                  'refresh_token':'fifa16-local-refresh',
                                  'expires_in':3600,'refresh_token_expires_in':86400})
        if refresh_grant_answered(form):
            # Run 1580: after expires_in, 3.0 sends this refresh grant and, unlike
            # v26 (held in 1004/1041, then a full code login), shows "servers
            # unavailable". AuthenticatorBase.refreshToken -> $13 -> onTokenResponse
            # -> NimbleIdentityToken(Map), the same parser as the code grant.
            return json_response({'access_token':'fifa16-local-access',
                                  'refresh_token':'fifa16-local-refresh',
                                  'expires_in':3600,'refresh_token_expires_in':86400})
    if (method=='GET' and headers.get(b'host')==b'10.0.2.2:18081'
        and headers.get(b'authorization')==b'null fifa16-local-access'):
        if url.path=='/proxy/identity/pids/me':
            # Run 18 observes this request. pidId is the only success predicate;
            # equals() dereferences every other string on subsequent refresh.
            # Empty metadata avoids fabricating demographics/profile semantics.
            pid={key:'' for key in ('anonymousPid','authenticationSource','country',
                  'dateCreated','dateModified','dob','language','lastAuthDate',
                  'locale','reasonCode','registrationSource','status','strength','tosVersion')}
            from server.local_profile import load_profile
            pid['pidId']=str(load_profile().identity_pid)
            return json_response({'pid':pid})
        if url.path=='/proxy/identity/pids/me/personas':
            from server.local_profile import load_profile
            # Controlled native refresh-gate experiment; no game/player fields.
            personas=[] if persona_id is None else [{'personaId':persona_id,
                'pidId':str(load_profile().identity_pid),'displayName':'','name':'','namespaceName':'',
                'status':'','statusReasonCode':'','showPersona':'',
                'dateCreated':'','lastAuthenticated':''}]
            return json_response({'personas':{'persona':personas}})
    return None


def refresh_grant_answered(form):
    """Exact captured refresh form, answered only for builds that opt in."""
    from . import client_build
    from .game_versions import version
    if version(client_build.version_code()).get('identity_refresh_grant') != 'answer':
        return False
    return (set(form) == {'grant_type', 'refresh_token', 'client_id', 'client_secret', 'redirect_uri'}
            and all(len(values) == 1 for values in form.values())
            and form['grant_type'] == ['refresh_token']
            and form['refresh_token'] == ['fifa16-local-refresh']
            and form['client_id'] == ['FIFA-WORLD-MOBILE-CLIENT-ANDROID']
            and form['client_secret'] == ['fifa16-local-lab']
            and form['redirect_uri'] == ['nucleus:rest'])
