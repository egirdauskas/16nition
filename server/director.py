#!/usr/bin/env python3
"""Observed Synergy director response, only enough to expose the next request.

The original parser accepts serverData key/value pairs and then requests a device
ID from synergy.user. Optional local Identity routes enable observed anonymous
authentication. This endpoint does not return player/token/session data.
"""
import argparse, datetime, json, socket, ssl, threading
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

HOST='syn-dir.sn.eamobile.com'
PATH='/director/api/android/getDirectionByPackage'
def response_for(request, user_base, identity_base=None):
    lines=request.split(b'\r\n')
    try:method,target,version=lines[0].decode('ascii').split()
    except (ValueError,UnicodeError):return None
    headers={}
    for line in lines[1:]:
        if b':' in line:
            key,value=line.split(b':',1);headers[key.lower()]=value.strip().decode('ascii',errors='replace')
    url=urlsplit(target);query=parse_qs(url.query)
    if method!='GET' or headers.get(b'host')!=HOST or url.path!=PATH:
        return None
    if query.get('packageId')!=['com.ea.gp.fifaworld']:
        return None
    # EnvironmentDataContainer.setGetDirectionResponseDictionary dereferences
    # all three Integer fields before it assigns the dictionary. Values are
    # from this supplied client's cached environment, recorded in run-12.
    data={'hwId':2363,'sellId':869639,'productId':55947,
          'serverData':[{'key':'synergy.user','value':user_base}]}
    if identity_base:
        # Run 14 and NimbleIdentityConfig require all three nonempty URLs.
        # This is lab configuration, not a production credential or token.
        data['clientSecret']='fifa16-local-lab'
        data['serverData'] += [{'key':key,'value':identity_base}
                              for key in ('nexus.connect','nexus.proxy','nexus.portal')]
    body=json.dumps(data,separators=(',',':')).encode()
    return b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body

def write(output, **event):
    event['utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    with output.open('a') as stream:stream.write(json.dumps(event)+'\n')

def handle(conn, peer, context, output, user_base, identity_base):
    try:
        conn.settimeout(8)
        with context.wrap_socket(conn,server_side=True) as tls:
            data=bytearray()
            while len(data)<65536 and b'\r\n\r\n' not in data:
                chunk=tls.recv(8192)
                if not chunk:break
                data.extend(chunk)
            response=response_for(bytes(data),user_base,identity_base)
            write(output,peer=peer,request=data.decode('latin1'),response_status=200 if response else None,response=response.decode('latin1') if response else None)
            if response:tls.sendall(response)
    except (ssl.SSLError,OSError) as error:
        write(output,peer=peer,tls_error=str(error));conn.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--port',type=int,default=18444);parser.add_argument('--user-base',default='http://10.0.2.2:18081');parser.add_argument('--identity-base');args=parser.parse_args()
    tlsdir=Path(__file__).resolve().parent/'tls'
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(tlsdir/'director.pem',tlsdir/'director-key.pem')
    def check_sni(conn,hostname,unused):
        if hostname!=HOST:return ssl.ALERT_DESCRIPTION_UNRECOGNIZED_NAME
    context.set_servername_callback(check_sni)
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);listener.bind(('127.0.0.1',args.port));listener.listen()
        while True:
            conn,peer=listener.accept();threading.Thread(target=handle,args=(conn,peer,context,args.output,args.user_base,args.identity_base),daemon=True).start()
if __name__=='__main__':main()
