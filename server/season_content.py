"""ID-only eligibility from supplied content; never copy football rows/assets."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from scripts.local_football_db import FootballDB
ROOT=Path(__file__).resolve().parents[1]

@lru_cache(maxsize=1)
def eligible_team_ids():
    db=ROOT/'native/content/main.13.com.ea.gp.fifaworld/data/db/fifa_ng_db.db'
    meta=db.with_name('fifa_ng_db-meta.xml')
    if sha256(db.read_bytes()).hexdigest()!='f4526c39b935ef7ce5a0e99a0568350d11997c6a18a6cea79c611ad3c150d105' or sha256(meta.read_bytes()).hexdigest()!='e6a6d54ac31b8eb9706675746eb48566a8258a75d58921e499d1535b6ef4d0c4':raise ValueError('Supplied content hash differs')
    source=FootballDB(db,meta)
    players={r['playerid'] for r in source.rows('players',['playerid'])}
    teams={r['teamid'] for r in source.rows('teams',['teamid'])}
    links={}
    for r in source.rows('teamplayerlinks',['teamid','playerid']):
        if r['teamid'] in teams and r['playerid'] in players:links.setdefault(r['teamid'],set()).add(r['playerid'])
    return frozenset(i for i,p in links.items() if i>0 and len(p)>=18)
