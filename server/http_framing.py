"""Preserve standard headers and the observed DirtySDK LF/CRLF terminator."""
def split_head(data):
    for terminator in (b'\r\n\r\n', b'\n\r\n'):
        if terminator in data:
            head, body = data.split(terminator, 1)
            return head, body, terminator
    return None

def read_request(conn, limit=65536):
    data = bytearray()
    while len(data) < limit and split_head(data) is None:
        chunk = conn.recv(min(8192, limit - len(data)))
        if not chunk:
            break
        data.extend(chunk)
    parts = split_head(data)
    if parts:
        head, body, terminator = parts
        lengths = [line.split(b':', 1)[1].strip() for line in head.splitlines()
                   if line.lower().startswith(b'content-length:')]
        needed = int(lengths[0]) if lengths else 0
        if not 0 <= needed <= limit:
            raise ValueError('Oversized request body')
        while len(body) < needed:
            chunk = conn.recv(min(8192, needed - len(body)))
            if not chunk:
                break
            body += chunk
            data.extend(chunk)
        if len(body) != needed:
            raise ValueError('Incomplete or excess request body')
    return bytes(data)
