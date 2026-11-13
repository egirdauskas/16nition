"""Scoped native Victory initialization candidate, derived from XML parser.

003161a0/00315508/00314f20 accept Persona and Session/UserWithPersonas/personas.
002fb500 dereferences the selected persona: default index0 needs one entry.
Only the established local persona is emitted. Success remains runtime-gated.
"""
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from .local_profile import load_profile
NS='http://schemas.datacontract.org/2004/07/Victory.AccountManagement.TransferObjects'
PATH='/victory_fwm_s2/Engine.svc/User/Authenticate'
# FIFA 16 3.0 (vc22, client build 112594), capture 1579: token, culture, build
# and device travel in the query string with an empty text/xml body. Its parser
# 00380ad8 -> 00313e70/00313ebc -> 00313228/00312c3c/00311378/003123bc is
# identical (normalized decompilation, same decoded keys) to v26 0038366c ->
# 00316154/003161a0 -> 00315508/00314f20/0031365c/003146a4, so the reply is
# the same AuthenticationResponse. Other builds stay unanswered (held).
BY_TOKEN_PATH='/victory_fwm_s2/Engine.svc/User/AuthenticateUserAndPersonaByToken'
BY_TOKEN_CLIENT_VERSIONS=frozenset({'112594'})
BY_TOKEN_QUERY_KEYS=frozenset({'token','cultureName','version','deviceId'})


def is_authentication(method,target):
    """Either captured Victory login form (v26 XML body or 3.0 query string)."""
    return method=='POST' and (target==PATH or target.split('?',1)[0]==BY_TOKEN_PATH)


def by_token_values(method,target,headers,body):
    """Exact 3.0 login request shape from capture 1579, or None."""
    from urllib.parse import parse_qs
    path,_,query=target.partition('?')
    if (method!='POST' or path!=BY_TOKEN_PATH or body
            or headers.get(b'host')!=b'10.0.2.2:18081'
            or headers.get(b'content-type',b'').split(b';',1)[0]!=b'text/xml'):
        return None
    try:
        values=parse_qs(query,keep_blank_values=True,strict_parsing=True)
    except ValueError:
        return None
    if set(values)!=BY_TOKEN_QUERY_KEYS or any(len(v)!=1 for v in values.values()):
        return None
    values={key:value[0] for key,value in values.items()}
    if (values['token']!='fifa16-local-victory-code' or values['cultureName']!='en_us'
            or values['version'] not in BY_TOKEN_CLIENT_VERSIONS or not values['deviceId'].isdigit()):
        return None
    return values


def authentication_response(profile,account):
    """AuthenticationResponse parsed by 003161a0 (v26) and 00313ebc (3.0)."""
    pid=str(profile.persona_id)
    payload=(f'<AuthenticationResponse xmlns="{NS}"><Persona><PersonaId>{pid}</PersonaId></Persona>'
             '<Session><UserWithPersonas><personas><Persona>'
             f'<PersonaId>{pid}</PersonaId></Persona></personas>'
             f'<user><SecurityToken>{escape(profile.victory_security_token)}</SecurityToken>'
             f'<UserId>{escape(profile.user_id)}</UserId></user></UserWithPersonas></Session>'
             '</AuthenticationResponse>').encode()
    from .welcome_gift import note
    note('authenticate', account)
    return xml_response(payload)
PROFILE_PLATE_PROJECTION=None
EARNED_XP_PROFILE=None
def configure_earned_xp(profile_path=None):
    global EARNED_XP_PROFILE
    from pathlib import Path
    path=Path(profile_path).resolve() if profile_path is not None else None
    if path is not None:
        root=Path(__file__).resolve().parents[1]
        from . import gameplay_release
        from .fresh_account_runtime import selected as fresh_selected
        released=gameplay_release.selected(path.parent)
        if released:gameplay_release.validate(path.parent)
        if (not released and not fresh_selected(path.parent) and (root/'reports' not in path.parents or path.parent.name!='isolated-account')) or Path(profile_path).is_symlink():
            raise ValueError('Earned XP candidate requires isolated reports profile')
        real=root/'server/data/development/fm16in2026/profile.json'
        if not released and real.exists() and path.samefile(real):raise ValueError('Real profile alias refused')
    EARNED_XP_PROFILE=path
def configure_plate_projection(policy=None,profile_path=None):
    global PROFILE_PLATE_PROJECTION
    from .profile_plate_projection import ProfilePlateProjection
    PROFILE_PLATE_PROJECTION=ProfilePlateProjection(policy,profile_path) if policy is not None else None
def xml_response(payload):
    if isinstance(payload,str):payload=payload.encode()
    return (b'HTTP/1.1 200 OK\r\nContent-Type: text/xml;charset=utf-8\r\nConnection: close\r\nContent-Length: '
            +str(len(payload)).encode()+b'\r\n\r\n'+payload)

def response_for(method,target,headers,body,persona_id):
    from .favorites import plate_xml, response_for as save_favorites
    from .match_record import plate_members
    from . import local_profile
    from pathlib import Path
    account=Path(local_profile.PROFILE_PATH).parent
    saved=save_favorites(method,target,headers,body)
    if saved:return saved
    profile=load_profile()
    if (method=='GET' and target in ('/victory_fwm_s2/Engine.svc/User/Persona/GetExtendedUserPlate','/victory_fwm_s2/Engine.svc/Settings/Client/','/victory_fwm_s2/Engine.svc/Message/Messages')
            and headers.get(b'host')==b'10.0.2.2:18081' and not body
            and headers.get(b'securitytoken')==profile.victory_security_token.encode()
            and headers.get(b'userid')==profile.user_id.encode()):
        # Root name is not checked. 00324ff8/00325044 retain constructor defaults
        # when no member is present; 002fd9c8 reads initialized empty strings/0s.
        namespace=('http://schemas.datacontract.org/2004/07/Victory.Service'
                   if target.endswith(('/Settings/Client/','/Message/Messages')) else
                   'http://schemas.datacontract.org/2004/07/Victory.FW.Components.AccountFeature.TransferObjects')
        if target.endswith('/Persona/GetExtendedUserPlate') and PROFILE_PLATE_PROJECTION is not None:
            if load_profile(PROFILE_PLATE_PROJECTION.path)!=profile:raise ValueError('Projection/profile selector mismatch')
            fields=PROFILE_PLATE_PROJECTION.fields()
            favorite=plate_xml(profile)+plate_members(account)
            members=''.join(f'<{name}>{value}</{name}>' for name,value in fields.items())
            return xml_response(f'<Response xmlns="{namespace}">{members}{favorite}</Response>')
        if target.endswith('/Persona/GetExtendedUserPlate') and EARNED_XP_PROFILE is not None:
            if load_profile(EARNED_XP_PROFILE)!=profile:raise ValueError('Earned XP profile selector mismatch')
            from .account_progression import level_state
            state=level_state(profile.revival_total_xp or 0)
            #614–617/768–769 prove these within-level display fields. The
            #GameReport callback itself requests this fresh snapshot.
            fields={'DeltaExperience':state['level_xp'],'DeltaLvExp':state['next_level_xp'],'Level':state['level']}
            members=''.join(f'<{k}>{v}</{k}>' for k,v in fields.items())
            favorite=plate_xml(profile)+plate_members(account)
            return xml_response(f'<Response xmlns="{namespace}">{members}{favorite}</Response>')
        if target.endswith('/Persona/GetExtendedUserPlate'):
            #00325044→00324a0c; team decoded in run247, country/player in run1523;
            #Record/LastFive (0034e3e4) in run1524.
            members=plate_xml(profile)+plate_members(account)
            if members:return xml_response(f'<Response xmlns="{namespace}">{members}</Response>')
        if target.endswith('/Message/Messages'):
            # FIRST-001: opt-in welcome popup/inbox strings (selector file per account).
            from . import welcome_gift
            strings = welcome_gift.pending(account)
            if strings:
                return xml_response(welcome_gift.messages_response(strings))
        return xml_response(f'<Response xmlns="{namespace}"/>')
    if by_token_values(method,target,headers,body) is not None:
        if persona_id!=profile.persona_id:return None
        return authentication_response(profile,account)
    if (method!='POST' or target!=PATH or headers.get(b'host')!=b'10.0.2.2:18081'
            or headers.get(b'content-type',b'').split(b';',1)[0]!=b'text/xml'
            or len(body)>8192):return None
    try:root=ET.fromstring(body)
    except ET.ParseError:return None
    if root.tag!='{'+NS+'}AuthenticationRequest':return None
    values={child.tag.rsplit('}',1)[-1]:child.text for child in root}
    if values.get('Token')!='fifa16-local-victory-code' or values.get('ClientVersion')!='113645':return None
    if not (values.get('DeviceId','').isdigit() and values.get('CultureName')=='en_us'):return None
    profile=load_profile()
    if persona_id!=profile.persona_id:return None
    return authentication_response(profile,account)
