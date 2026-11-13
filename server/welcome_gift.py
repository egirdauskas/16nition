"""FIRST-001 welcome gift: login-gift popup and inbox message (revival_policy welcome_gift_v1).

Wire contracts are statically mapped in reports/first-001/2026-11-07-welcome-gift/report.md:
Message/Messages carries a list of strings; each string is an XML document whose root name the
client dispatches on. `ShowPopup` becomes VictoryClient::LoginGiftPopup (stock LoginGiftOverlay);
`MessageCentreMessage` becomes an inbox entry. Texts are localization keys served with the
existing downloaded localization.

Delivery is per account and opt-in: only an account directory holding a valid selector file is
served. Phase 1 (this module) delivers messages only; it grants nothing.
"""
from copy import deepcopy
import hashlib
import json
import threading
import time
from pathlib import Path
from xml.sax.saxutils import escape

from .policy_memo import policy_memo

POLICY = Path(__file__).parent / 'policy' / 'welcome-gift-v1.json'
SELECTOR = 'welcome-gift.json'
SELECTOR_VERSION = 'welcome_gift_selection_v1'
POPUP_NS = 'http://schemas.datacontract.org/2004/07/Victory.Service'
INBOX_NS = 'http://schemas.datacontract.org/2004/07/Victory.FW.Components.AccountFeature.TransferObjects'
RESPONSE_NS = 'http://schemas.datacontract.org/2004/07/Victory.TransferObjects'
ARRAYS_NS = 'http://schemas.microsoft.com/2003/10/Serialization/Arrays'
# FUN_00303d04 field limits (characters).
LIMITS = {'PopupType': 32, 'HeadingTextHALId': 64, 'BodyTextHALId': 64, 'ImageFile': 512,
          'ButtonTextHALId': 64, 'TakeMeTo': 32}


# Per-login readiness (capture 2026-11-07): delivering on the first poll after Authenticate
# localized the inbox entry before the downloaded texts arrived (Messages 20:06:31.400,
# Challenges.xml 20:06:31.600). Deliver only after this login has fetched the texts.
_LOCK = threading.Lock()
_SESSION = {'authenticate': 0.0, 'localization': 0.0, 'finalize': 0.0}
_READINESS_CACHE = {}
READINESS_VERSION = 'welcome_readiness_v1'


def readiness_path(account):
    account = Path(account).resolve()
    return account.with_name('.' + account.name + '.welcome-readiness.json')


def _owner(account):
    from .first_run_account import pending_session
    if _load(account) is None and pending_session(account) is None:
        return None
    from .local_profile import load_profile
    return load_profile(Path(account) / 'profile.json').user_id


def _read_readiness(account):
    path = readiness_path(account)
    if not path.exists():
        return None
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).digest()
    if digest not in _READINESS_CACHE:
        value = json.loads(raw)
        if (set(value) != {'version', 'account', 'user_id', 'localized'}
                or value['version'] != READINESS_VERSION
                or type(value['account']) is not str or type(value['user_id']) is not str
                or type(value['localized']) is not bool):
            raise ValueError('Invalid welcome readiness record')
        if len(_READINESS_CACHE) >= 32:
            _READINESS_CACHE.clear()
        _READINESS_CACHE[digest] = value
    value = deepcopy(_READINESS_CACHE[digest])
    if value['account'] != str(Path(account).resolve()) or value['user_id'] != _owner(account):
        raise ValueError('Welcome readiness owner conflict')
    return value


def _write_readiness(account, user_id, localized):
    from .account_transaction import atomic
    value = {'version': READINESS_VERSION, 'account': str(Path(account).resolve()),
             'user_id': user_id, 'localized': localized}
    atomic(readiness_path(account), (json.dumps(value, indent=2, sort_keys=True) + '\n').encode())


def note(event, account=None):
    """Keep actual localization delivery readiness through backend recovery."""
    if event not in _SESSION:
        raise ValueError('Unknown welcome milestone')
    with _LOCK:
        _SESSION[event] = time.monotonic()
        if account is None or event not in ('authenticate', 'localization'):
            return
        user_id = _owner(account)
        if user_id is not None:
            # A genuine new authentication clears the previous client's text
            # readiness. A server restart alone leaves the record unchanged.
            _write_readiness(account, user_id, event == 'localization')


def ready(account=None):
    with _LOCK:
        if account is not None:
            value = _read_readiness(account)
            if value is not None:
                return value['localized']
        return _SESSION['localization'] > _SESSION['authenticate']


def recover_readiness(account, log_path):
    """One-time upgrade from genuine logged replies, not request/event replay.

    New code records these milestones directly. Older running clients can retain
    downloaded texts across a backend upgrade, so recover only a matching owner
    authentication followed by the actual successful localization response.
    """
    owner = _owner(account)
    if owner is None or readiness_path(account).exists():
        return None
    value = _load(account)
    if value is not None and {'popup', 'inbox'} <= set(value['served'].get(str(value['generation']), [])):
        return None
    import xml.etree.ElementTree as ET
    authenticated = False
    localized = False
    evidence = None
    expected = dict(localization_units())
    log_path = Path(log_path)
    if log_path.exists():
        with log_path.open() as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    target = row.get('request', '').split('\r\n', 1)[0].split()
                    if len(target) != 3 or row.get('response_status') != 200 or not row.get('response'):
                        continue
                    body = row['response'].encode('latin1').split(b'\r\n\r\n', 1)[1]
                    if target[:2] == ['POST', '/victory_fwm_s2/Engine.svc/User/Authenticate']:
                        root = ET.fromstring(body)
                        users = [node.text for node in root.iter() if node.tag.rsplit('}', 1)[-1] == 'UserId']
                        authenticated = users == [owner]
                        localized = False
                    elif authenticated and target[:2] == ['GET', '/loc/en_us/Challenges.xml']:
                        root = ET.fromstring(body)
                        units = {node.get('resname'): node.findtext('source')
                                 for node in root.iter('trans-unit')}
                        if all(units.get(key) == text for key, text in expected.items()):
                            localized = True
                            evidence = hashlib.sha256(line.encode()).hexdigest()
                except (ValueError, KeyError, IndexError, UnicodeError, ET.ParseError):
                    continue
    _write_readiness(account, owner, localized)
    return {'localized': localized, 'localization_record_sha256': evidence}


@policy_memo
def policy():
    value = json.loads(POLICY.read_text())
    if value.get('classification') != 'revival_policy' or value.get('version') != 'welcome_gift_v1':
        raise ValueError('Invalid welcome gift policy')
    return value


def localization_units():
    value = policy()
    popup = value['popup']
    return [tuple(popup[k]) for k in ('heading', 'body', 'button')] + [tuple(value['inbox'])]


def popup_xml(image_file=None):
    popup = policy()['popup']
    # Capture 2026-11-07: the client requests GET /<ImageFile> on its content host, so
    # ImageFile is a relative path, never an absolute URL.
    image_url = popup['image_file'] if image_file is None else image_file
    fields = {
        'BodyTextHALId': popup['body'][0],
        'ButtonTextHALId': popup['button'][0],
        'HeadingTextHALId': popup['heading'][0],
        'ImageFile': image_url,
        'PopupType': popup['popup_type'],
        'TakeMeTo': popup['take_me_to'],
    }
    # LoginGiftOverlay (decompiled) publishes imageFile to the view as a downloaded-image cache
    # name and matches downloads with string.find(imageFile, data.image): keep it a flat file
    # name without directories or Lua pattern characters.
    if any(c in fields['ImageFile'] for c in '/-%()[]*+?^$'):
        raise ValueError('ImageFile must be a flat name without Lua pattern characters')
    for name, text in fields.items():
        if len(text) > LIMITS[name]:
            raise ValueError('%s exceeds the client field limit' % name)
    members = ''.join('<%s>%s</%s>' % (k, escape(v), k) for k, v in fields.items())
    return '<ShowPopup xmlns="%s">%s</ShowPopup>' % (POPUP_NS, members)


def inbox_xml():
    key = policy()['inbox'][0]
    return '<MessageCentreMessage xmlns="%s"><MessageHALId>%s</MessageHALId></MessageCentreMessage>' % (
        INBOX_NS, escape(key))


def messages_response(strings):
    items = ''.join('<a:string>%s</a:string>' % escape(s) for s in strings)
    return ('<Response xmlns="%s"><Messages xmlns:a="%s">%s</Messages></Response>'
            % (RESPONSE_NS, ARRAYS_NS, items))


def _load(account):
    path = Path(account) / SELECTOR
    if not path.exists():
        return None
    value = json.loads(path.read_bytes())
    if (type(value) is not dict or value.get('version') != SELECTOR_VERSION
            or value.get('account') != str(Path(account).resolve())
            or type(value.get('generation')) is not int or type(value.get('served')) is not dict):
        raise ValueError('Invalid welcome gift selector')
    return value


def image_response(method, target, headers, body):
    """Serve the popup background requested as GET /<ImageFile>."""
    popup = policy()['popup']
    if method != 'GET' or body or target != '/' + popup['image_file'] or headers.get(b'host') != b'10.0.2.2:18081':
        return None
    raw = (Path(__file__).resolve().parents[1] / popup['image_asset']).read_bytes()
    # Answer immediately: a 5 s delayed reply (gen 5/7) left the image undrawn.
    return (b'HTTP/1.1 200 OK\r\nContent-Type: image/png\r\nConnection: close\r\nContent-Length: '
            + str(len(raw)).encode() + b'\r\n\r\n' + raw)


def pending(account, image_file=None):
    """Message strings still to deliver for this account; records them as served (atomic)."""
    value = _load(account)
    if value is None or not ready(account):
        return []
    generation = str(value['generation'])
    served = value['served'].setdefault(generation, [])
    out = []
    for kind, text in (('popup', popup_xml(image_file)), ('inbox', inbox_xml())):
        if kind not in served:
            out.append(text)
            served.append(kind)
    if out:
        from .account_transaction import atomic
        atomic(Path(account) / SELECTOR, (json.dumps(value, indent=2, sort_keys=True) + '\n').encode())
    return out


def select(account, generation):
    """Opt an account in (lab use). A new generation re-delivers both messages."""
    account = Path(account).resolve()
    value = _load(account) or {'version': SELECTOR_VERSION, 'account': str(account), 'served': {}}
    value['generation'] = generation
    from .account_transaction import atomic
    atomic(account / SELECTOR, (json.dumps(value, indent=2, sort_keys=True) + '\n').encode())
    return value
