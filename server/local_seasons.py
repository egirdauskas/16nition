"""Local competition rules and account progress, separate from RS4 encoding.

Fresh creation and sequential legacy progress within the existing season.
Native player/match records stay opaque; no economy or football-item writes.
No player assets, historical progress, economy or cache flags are stored.
"""
from dataclasses import dataclass,asdict
import json,os,tempfile,fcntl
from pathlib import Path
from .season_content import eligible_team_ids
from .season_blob import decode_envelope,validated_progress
from .season_progression import validate_progress,reconcile

@dataclass(frozen=True)
class Fixture:
    team_id:int
    difficulty:int
    round_number:int

@dataclass(frozen=True)
class CompetitionDefinition:
    season_id:int
    division_index:int
    match_minutes:int
    fixtures:tuple

    def validate(self):
        if type(self.season_id) is not int or self.season_id<=0 or type(self.division_index) is not int or not 0<=self.division_index<=10 or type(self.match_minutes) is not int or self.match_minutes!=6:
            raise ValueError('Unsupported local competition rules')
        if len(self.fixtures)!=10 or len({x.team_id for x in self.fixtures})!=10:
            raise ValueError('Measured offline controller requires ten distinct local fixtures')
        for i,f in enumerate(self.fixtures,1):
            if type(f.team_id) is not int or f.team_id<=0 or type(f.difficulty) is not int or f.difficulty!=0 or type(f.round_number) is not int or f.round_number!=i:
                raise ValueError('Invalid local fixture')
            if f.team_id not in eligible_team_ids():raise ValueError('Fixture team has no coherent supplied roster')
        return self

def load_definition(path):
    value=json.loads(Path(path).read_text())
    return definition_from_data(value)

def definition_from_data(value):
    if 'choices_version' in value:
        from .season_choices import ChoiceDefinition
        if set(value)!={'season_id','division_index','match_minutes','fixtures','choices_version',
                         'competition_key','fixture_seed','catalog_sha256'}:
            raise ValueError('Unexpected selected competition fields')
        return ChoiceDefinition(**{**value,'fixtures':tuple(Fixture(**f) for f in value['fixtures'])}).validate()
    if set(value)!={'season_id','division_index','match_minutes','fixtures'}:
        raise ValueError('Unexpected definition fields')
    return CompetitionDefinition(value['season_id'],value['division_index'],value['match_minutes'],tuple(Fixture(**f) for f in value['fixtures'])).validate()

@dataclass(frozen=True)
class CurrentSeason:
    season_id:int
    division_index:int
    round_number:int
    user_points:int
    client_state_hex:str
    client_state_envelope_hex:str|None=None

    def validate(self,definition):
        if (type(self.season_id) is not int or self.season_id!=definition.season_id or
            type(self.division_index) is not int or self.division_index!=definition.division_index or
            type(self.round_number) is not int or not 1 <= self.round_number <= len(definition.fixtures) + 1 or
            type(self.user_points) is not int or type(self.client_state_hex) is not str):
            raise ValueError('Invalid local season identity/progress')
        try:raw=bytes.fromhex(self.client_state_hex)
        except ValueError as exc:raise ValueError('Invalid season bytes') from exc
        if self.user_points!=validated_progress(raw,self.round_number):
            raise ValueError('Points must match proven native TP header')
        validate_progress(self.round_number-1,self.user_points)
        if self.client_state_envelope_hex is not None:
            if type(self.client_state_envelope_hex) is not str:raise ValueError('Invalid opaque envelope')
            if decode_envelope(bytes.fromhex(self.client_state_envelope_hex))!=raw:raise ValueError('Envelope does not match preserved payload')
        elif self.round_number!=1:
            raise ValueError('Post-match state must retain original envelope')
        return self

class SeasonStore:
    def __init__(self,path,definition,persona_id=1):
        if type(persona_id) is not int or persona_id!=1:raise ValueError('Unknown persona')
        self.path=Path(path);self.definition=definition.validate();self.persona_id=persona_id
    def load(self):
        if not self.path.exists():return None
        value=json.loads(self.path.read_text())
        if set(value)!={'persona_id','current'} or value['persona_id']!=self.persona_id or type(value['persona_id']) is not int:raise ValueError('Wrong season owner/envelope')
        return CurrentSeason(**value['current']).validate(self.definition) if value['current'] is not None else None
    def save(self,current):
        # Serialise compare-and-replace across server threads/processes. Atomic
        # replacement alone cannot reject two distinct saves for one fixture.
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.with_name(self.path.name+'.lock').open('a') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
            try:return self._save_locked(current)
            finally:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)

    def _save_locked(self,current):
        current.validate(self.definition)
        old=self.load()
        if old==current:return old  # Idempotent repeat of original client save.
        if old is None and current.round_number!=1:raise ValueError('Cannot create a progressed season')
        if old is not None and current.round_number != old.round_number + 1:
            raise ValueError('Only one stock round may advance per save')
        if old is not None:
            reconcile(old.round_number-1,old.user_points,current.round_number-1,current.user_points)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix=self.path.name+'.',suffix='.new',dir=self.path.parent)
        temporary=Path(name)
        try:
            with os.fdopen(fd,'w') as stream:
                stream.write(json.dumps({'persona_id':self.persona_id,'current':asdict(current)},indent=2,sort_keys=True)+'\n')
                stream.flush();os.fsync(stream.fileno())
            temporary.replace(self.path)
            directory=os.open(self.path.parent,os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:
            if temporary.exists():temporary.unlink()
        return current
