"""Transport adapter for the authorized localhost-only game copy.

The recovered domain adapters retain their canonical lab Host contract. Only
the loopback embedding calls this adapter; actual request bytes stay in logs.
"""
from urllib.parse import urlsplit

from . import director, http_framing

LOCAL_HOSTS = {b'127.0.0.1:18081', b'localhost:18081'}
CANONICAL = b'10.0.2.2:18081'


def canonical_request(data):
    parts = http_framing.split_head(data)
    if parts is None:
        return data
    head = parts[0]
    hosts = [line for line in head.splitlines()[1:]
             if line.split(b':', 1)[0].lower() == b'host']
    if len(hosts) != 1:
        return data
    line = hosts[0]
    if line.split(b':', 1)[1].strip().lower() not in LOCAL_HOSTS:
        return data
    return data.replace(line, b'Host: ' + CANONICAL, 1)


def bootstrap_response(data):
    parts = http_framing.split_head(data)
    if parts is None:
        return None
    head, body, _ = parts
    method, target, version = head.splitlines()[0].decode('ascii').split()
    hosts = [line.split(b':', 1)[1].strip().lower() for line in head.splitlines()[1:]
             if line.split(b':', 1)[0].lower() == b'host']
    if hosts != [CANONICAL] or version != 'HTTP/1.1' or body:
        return None
    if method == 'GET' and target == '/':
        from .reachability import OK
        return OK
    if urlsplit(target).path == director.PATH:
        # Same captured director request/response; only its transport origin
        # and returned local address change for the private on-device server.
        request = data.replace(b'Host: ' + CANONICAL,
                               b'Host: ' + director.HOST.encode(), 1)
        return director.response_for(request, 'http://127.0.0.1:18081',
                                     'http://127.0.0.1:18081')
    return None
