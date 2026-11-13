"""Minimal local profile, independent of XML/RS4 protocol envelopes.

Observed identity/session state, currencies and opt-in club preferences only.
Football ownership and competition progress belong to separate domain stores.
"""
from dataclasses import dataclass, asdict, replace
import json
import os
import tempfile
import fcntl
from contextlib import contextmanager
from pathlib import Path
PROFILE_PATH=Path(__file__).parent/'data/local-profile.json'
@dataclass(frozen=True)
class LocalProfile:
    identity_pid:int
    persona_id:int
    user_id:str
    victory_security_token:str
    credits:int=0
    fifa_points:int=0
    club_name:str|None=None
    division_offline:int|None=None
    favorite_team_id:int|None=None
    revival_total_xp:int|None=None
    club_abbreviation:str|None=None
    favorite_country_id:int|None=None
    favorite_player_id:int|None=None

def configure_profile(path):
    """Select an explicit local account once at service startup."""
    global PROFILE_PATH
    PROFILE_PATH=Path(path)

def validate_credits(value):
    # The native currency parser stores the integer's low32 bits; UI treats
    # balances as signed32. Do not silently wrap or accept bool as an integer.
    if type(value) is not int or not 0<=value<=0x7fffffff:
        raise ValueError('Credits must be a nonnegative signed32 integer')
    return value

def load_profile(path=None):
    selected = Path(path or PROFILE_PATH)
    if not selected.exists():
        from .first_run_account import pending_profile
        pending = pending_profile(selected)
        if pending is not None:
            return pending
    value=json.loads(selected.read_text())
    pid=value['identity_pid']
    if type(pid) is not int or pid<=0:raise ValueError('Invalid established local identity')
    persona=value['persona_id']
    if type(persona) is not int or persona<=0:raise ValueError('Invalid established local persona')
    user=value['user_id'];token=value['victory_security_token']
    if not all(isinstance(v,str) and v and v.isascii() for v in (user,token)):
        raise ValueError('Invalid local opaque Victory identifiers')
    credits=validate_credits(value.get('credits',0))
    points=validate_credits(value.get('fifa_points',0))
    club=value.get('club_name')
    if club is not None and (type(club) is not str or not club.isascii() or not 1<=len(club)<=29 or any(ord(c)<32 for c in club)):
        raise ValueError('Invalid bounded native club label')
    division=value.get('division_offline')
    if division is not None and (type(division) is not int or not 0<=division<=10):
        raise ValueError('Invalid local/revival offline division')
    favorite=value.get('favorite_team_id')
    if favorite is not None:
        from .season_content import eligible_team_ids
        if type(favorite) is not int or favorite not in eligible_team_ids():raise ValueError('Unknown supplied favorite team')
    xp=value.get('revival_total_xp')
    if xp is not None and (type(xp) is not int or xp<0):raise ValueError('Invalid revival XP')
    abbreviation=value.get('club_abbreviation')
    if abbreviation is not None and (type(abbreviation) is not str or len(abbreviation)!=3 or
            not abbreviation.isascii() or any(ord(c)<32 for c in abbreviation) or not abbreviation.strip()):
        raise ValueError('Invalid bounded native club abbreviation')
    country=value.get('favorite_country_id')
    player=value.get('favorite_player_id')
    if country is not None or player is not None:
        from .favorites import valid_country,valid_player
        if not valid_country(country):raise ValueError('Unknown supplied favorite country')
        if not valid_player(player):raise ValueError('Unknown supplied favorite player')
    return LocalProfile(pid,persona,user,token,credits,points,club,division,favorite,xp,abbreviation,country,player)

class ProfileStore:
    """One local profile; deterministic JSON and atomic durable replacement.

    Existing identity-only profiles read as a fresh zero-coin account. GETs
    never mutate balances. Future mutations must use this domain interface.
    """
    def __init__(self,path=None):self.path=Path(path or PROFILE_PATH)
    def load(self):return load_profile(self.path)
    def save(self,profile):
        validate_credits(profile.credits)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        descriptor,name=tempfile.mkstemp(prefix=self.path.name+'.',suffix='.new',dir=self.path.parent)
        temporary=Path(name)
        try:
            with os.fdopen(descriptor,'w') as stream:
                value=asdict(profile)
                if not profile.fifa_points:value.pop('fifa_points')
                if profile.club_name is None:value.pop('club_name')
                if profile.division_offline is None:value.pop('division_offline')
                if profile.favorite_team_id is None:value.pop('favorite_team_id')
                if profile.revival_total_xp is None:value.pop('revival_total_xp')
                if profile.club_abbreviation is None:value.pop('club_abbreviation')
                if profile.favorite_country_id is None:value.pop('favorite_country_id')
                if profile.favorite_player_id is None:value.pop('favorite_player_id')
                stream.write(json.dumps(value,indent=2,sort_keys=True)+'\n')
                stream.flush();os.fsync(stream.fileno())
            # Validate the complete profile before replacing the last good file.
            load_profile(temporary)
            temporary.replace(self.path)
            directory=os.open(self.path.parent,os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:
            if temporary.exists():temporary.unlink()
    def set_credits(self,value):
        with self.transaction():
            profile=replace(self.load(),credits=validate_credits(value))
            self.save(profile);return profile
    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.with_name(self.path.name+'.lock').open('a') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)
