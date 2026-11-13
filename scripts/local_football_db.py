#!/usr/bin/env python3
"""Read-only supplied T3DB integer rows using its accompanying metadata.

No network/assets exported to the backend. Table offsets are relative to the
end of the file's table directory. Integer fields are packed little-endian bits;
metadata rangelow supplies their bias. Header/row validity is checked explicitly.
"""
import argparse,json,struct
from pathlib import Path
from xml.etree import ElementTree as ET
DB=Path('native/content/main.13.com.ea.gp.fifaworld/data/db/fifa_ng_db.db')
META=DB.with_name('fifa_ng_db-meta.xml')
class FootballDB:
 def __init__(self,path=DB,meta=META):
  self.data=path.read_bytes();assert self.data[:4]==b'DB\0\x08'
  self.meta={t.get('name'):t for t in ET.parse(meta).getroot().findall('table')}
  count=struct.unpack_from('<I',self.data,16)[0];assert count==len(self.meta)
  self.base=32+count*8
  self.directory={self.data[i:i+4].decode():struct.unpack_from('<I',self.data,i+4)[0]+self.base for i in range(24,24+count*8,8)}
 def table(self,name):
  schema=self.meta[name];start=self.directory[schema.get('shortname')]
  size=struct.unpack_from('<I',self.data,start)[0];count=struct.unpack_from('<H',self.data,start+12)[0]
  fields=struct.unpack_from('<I',self.data,start+20)[0]
  meta={f.get('shortname'):f for f in schema.find('fields')}
  assert fields==len(meta)
  columns={}
  for i in range(fields):
   kind,bit,key,depth=struct.unpack_from('<II4sI',self.data,start+32+i*16)
   f=meta[key.decode()];assert depth==int(f.get('depth'))
   columns[f.get('name')]={'kind':kind,'bit':bit,'depth':depth,'bias':int(f.get('rangelow'))}
  # Header includes its CRC; records directly follow the field descriptors.
  first=start+32+fields*16
  assert first+count*size<=len(self.data)
  return {'start':start,'size':size,'count':count,'valid_count':struct.unpack_from('<H',self.data,start+14)[0],
          'columns':columns,'first':first}
 def rows(self,name,fields):
  t=self.table(name)
  for i in range(t['count']):
   offset=t['first']+i*t['size'];row=int.from_bytes(self.data[offset:offset+t['size']],'little');out={}
   for f in fields:
    c=t['columns'][f];assert c['kind']==3
    out[f]=((row>>c['bit'])&((1<<c['depth'])-1))+c['bias']
   yield {'row_index':i,'row_offset':offset,**out}
 def compressed_text(self,name,row_index,field):
  """Read the supplied type13 Huffman field; no database writes.

  Row contains a32-bit byte offset from the row-data end. The pool starts
  with a binary tree of two little-endian16-bit edges per node: an edge with
  a nonzero high byte is a terminal byte, otherwise it is a node index.
  String data is byte length followed by MSB-first encoded bits. Decode only
  within this table's preserved pool;0xffffffff is the null string sentinel.
  """
  t=self.table(name);c=t['columns'][field]
  if c['kind']!=13 or c['bit']%8:raise ValueError('Not an aligned compressed-string field')
  if not 0<=row_index<t['count']:raise ValueError('Row outside table')
  pool=t['first']+t['size']*t['count']
  bound=min((v for v in self.directory.values() if v>t['start']),default=len(self.data))
  pos=t['first']+row_index*t['size']+c['bit']//8
  offset=struct.unpack_from('<I',self.data,pos)[0]
  if offset==0xffffffff:return ''
  if not 0<=offset<bound-pool:raise ValueError('Compressed string offset outside supplied table')
  pos=pool+offset;n=self.data[pos];node=0;result=bytearray()
  if not n:return ''
  for byte in self.data[pos+1:bound]:
   for bit in range(7,-1,-1):
    edge=pool+node*4+((byte>>bit)&1)*2
    if not pool<=edge<pos-1:raise ValueError('Invalid supplied Huffman tree')
    code=struct.unpack_from('<H',self.data,edge)[0]
    if code>>8:
     if code&255:raise ValueError('Invalid supplied terminal')
     result.append(code>>8);node=0
     if len(result)==n:return result.decode('utf8')
    else:node=code
  raise ValueError('Truncated supplied compressed string')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('table');p.add_argument('fields',nargs='+');p.add_argument('--limit',type=int,default=10);a=p.parse_args()
 db=FootballDB();print(json.dumps(db.table(a.table),indent=2))
 for i,row in enumerate(db.rows(a.table,a.fields)):
  if i>=a.limit:break
  print(json.dumps(row))
