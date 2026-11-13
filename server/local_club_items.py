"""Supplied club cards for prospective mixed packs; no static account metadata.

01027c20 resolves badge11,kit9,stadium10;010275ac resolves ball30.
Native enrichment reads value as quality/rating, category is a club-item kind
(for example home/away kit), not Bronze/Silver/Gold. Pack odds are revival policy.
"""
from functools import lru_cache
from .local_content_source import DB,META,cards
from scripts.local_football_db import FootballDB

POOL='supplied_club_items_v1'
SUBTYPES={'badge':11,'kit':9,'stadium':10,'ball':30}
TABLES={'badge':'fcc_badgecards','kit':'fcc_kitcards','stadium':'fcc_stadium','ball':'fcc_balls'}

@lru_cache(maxsize=1)
def references():
    cards()  # Existing supplied DB/meta hash validation.
    db=FootballDB(DB,META);result={}
    for kind,table in TABLES.items():
        limit=db.table(table)['valid_count']
        rarity='rare' if kind=='ball' else 'weightrare'
        seen={}
        fields=[k for k,v in db.table(table)['columns'].items() if v['kind']==3]
        for row in db.rows(table,fields):
            if row['row_index']>=limit:continue
            rid=row['carddbid']
            if type(rid) is not int or rid<=0 or not 1<=row['value']<=99:
                raise ValueError('Invalid supplied club-card identity/value')
            # fcc_balls has197 valid rows but129 unique resources, with68
            # repeated rows. Count a resource once, never weight duplicates.
            raw={k:row[k] for k in fields}
            if rid in seen:
                if seen[rid]!=raw:raise ValueError('Conflicting supplied club-card rows')
                continue
            if rid in result:raise ValueError('Cross-family club-card identity collision')
            seen[rid]=raw
            result[rid]={'item_type':kind,'subtype':SUBTYPES[kind],
                'rating':row['value'],'rare':int(row[rarity]>0)}
    return result

def reference(kind,resource_id):
    row=references().get(resource_id) if type(resource_id) is int else None
    if row is None or row['item_type']!=kind:raise ValueError('Unknown/mismatched supplied club card')
    return row

def quality(row):
    return 'gold' if row['rating']>=75 else 'silver' if row['rating']>=65 else 'bronze'
