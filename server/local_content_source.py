"""Read-only supplied card and club-resource resolver; no static rows in state.

The football domain owns identifiers. This protocol enrichment reads only the
observed display scalars and identifier references from the locally supplied database, retained under native/.
Source hashes are the run124 validated DB/meta, not live content.
"""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from scripts.local_football_db import FootballDB
ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'native/content/main.13.com.ea.gp.fifaworld/data/db/fifa_ng_db.db'
META=DB.with_name('fifa_ng_db-meta.xml')
@lru_cache(maxsize=1)
def cards():
 if sha256(DB.read_bytes()).hexdigest()!='f4526c39b935ef7ce5a0e99a0568350d11997c6a18a6cea79c611ad3c150d105':raise ValueError('Supplied content hash differs')
 if sha256(META.read_bytes()).hexdigest()!='e6a6d54ac31b8eb9706675746eb48566a8258a75d58921e499d1535b6ef4d0c4':raise ValueError('Supplied metadata hash differs')
 fields=['carddbid','rating','preferredposition','rare']+[f'attribute{i}' for i in range(1,7)]
 rows=FootballDB(DB,META).rows('fcc_playercards',fields)
 return {r['carddbid']:(r['rating'],r['preferredposition'],r['rare'],
                       tuple(r[f'attribute{i}'] for i in range(1,7))) for r in rows}
def rating_for(resource_id):
 row=cards().get(resource_id)
 value=row[0] if row else None
 if type(value) is not int or not 0<value<=99:raise ValueError('No valid supplied card rating')
 return value

# Exact17 accepted pairs from0103081c/table027aa630, not modern FUT strings.
POSITION_WIRE={0:'GK',2:'RWB',3:'RB',5:'CB',7:'LB',8:'LWB',10:'CDM',12:'RM',14:'CM',16:'LM',18:'CAM',20:'RF',21:'CF',22:'LF',23:'RW',25:'ST',27:'LW'}
def position_for(resource_id):
 row=cards().get(resource_id)
 if row is None or row[1] not in POSITION_WIRE:raise ValueError('No accepted supplied card position')
 return POSITION_WIRE[row[1]]

def rarity_for(resource_id):
 row=cards().get(resource_id)
 if row is None or row[2] not in (0,1):raise ValueError('Unsupported supplied base-card rarity')
 return row[2]

def attributes_for(resource_id):
 """Six base display stats, not account condition or gameplay proposals.

 Shared decoder01028fc0 accepts attributeList[index,value]. Frontend00b5bff8
 reads indices0..5 through01a3c018 from item+6a+2*index. Indices6/7 overlap
 separately enriched morale/fitness, so those are deliberately not encoded.
 """
 row=cards().get(resource_id)
 if row is None or len(row[3])!=6 or any(type(v) is not int or not 0<=v<=99 for v in row[3]):
  raise ValueError('No valid supplied card display attributes')
 return row[3]

@lru_cache(maxsize=1)
def badges():
 cards()  # verify the same supplied DB/meta hashes
 return {r['carddbid']:(r['teamid'],r['assetid']) for r in FootballDB(DB,META).rows('fcc_badgecards',['carddbid','teamid','assetid'])}

def badge_for(resource_id):
 if type(resource_id) is not int or resource_id not in badges():raise ValueError('Unknown supplied badge resource')
 return badges()[resource_id]

@lru_cache(maxsize=1)
def club_resources():
 cards()
 db=FootballDB(DB,META)
 result={}
 for row in db.rows('fcc_kitcards',['carddbid','teamid','assetid','category']):result[('kit',row['carddbid'])]=row
 for row in db.rows('fcc_stadium',['carddbid','stadiumid','assetid','category']):result[('stadium',row['carddbid'])]=row
 return result

def club_resource_for(item_type,resource_id):
 if type(resource_id) is not int or (item_type,resource_id) not in club_resources():raise ValueError('Unknown supplied club resource')
 return club_resources()[item_type,resource_id]

@lru_cache(maxsize=1)
def managers():
 cards() # shared supplied DB/meta integrity check
 db=FootballDB(DB,META);valid=db.table('managercards')['valid_count']
 return {r['carddbid']:r for r in db.rows('managercards',['carddbid','assetid','nation','formationid','rare','value'])
         if r['row_index']<valid and r['carddbid']>0}

def manager_for(resource_id):
 if type(resource_id) is not int or resource_id not in managers():raise ValueError('Unknown supplied manager card')
 return managers()[resource_id]

def find_manager(firstname,lastname):
 """Operator selection through supplied compressed fields, never a name fixture."""
 cards();db=FootballDB(DB,META)
 matches=[r['carddbid'] for r in managers().values() if
          db.compressed_text('managercards',r['row_index'],'firstname')==firstname and
          db.compressed_text('managercards',r['row_index'],'lastname')==lastname]
 if len(matches)!=1:raise ValueError('Manager name does not identify one supplied card')
 return matches[0]
