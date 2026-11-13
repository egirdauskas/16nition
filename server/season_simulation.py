"""Opt-in isolated backend Seasons, never an RS4 or opaque-state generator.

The journal is authoritative. Durable intent -> ProfileStore -> committed event
is a recoverable cross-file transaction, not a claim of filesystem atomicity.
"""
from contextlib import contextmanager
from dataclasses import asdict,replace
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from .account_transaction import account_locked
from .local_profile import ProfileStore,validate_credits
from .local_seasons import SeasonStore,load_definition
from .season_revival_policy import POLICY,load_policy
from .season_progression import POINTS,advance

ROOT=Path(__file__).resolve().parents[1]
REAL=ROOT/'server/data/development/fm16in2026'
MARKER='.simulation-isolation.json'
JOURNAL='simulation.json'
POLICY_COPY='simulation-policy.json'

def digest(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,indent=2,sort_keys=True)+'\n').encode()
def identity(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}',value):
        raise ValueError('Explicit bounded request ID required')
    return value
def integer(value,low,high):
    if type(value) is not int or not low<=value<=high:raise ValueError('Invalid integer bound')
    return value
def profile_fields(profile):
    value=asdict(profile);value.pop('credits')
    if value.get('club_abbreviation') is None:value.pop('club_abbreviation',None)
    # Favourite country/player (run 1523) are absent from older anchors when unset.
    for key in ('favorite_country_id','favorite_player_id'):
        if value.get(key) is None:value.pop(key,None)
    # Old journals predate revival XP. Absent XP must preserve their exact
    # non-wallet anchor, while populated XP remains protected from overwrite.
    if value['revival_total_xp'] is None:value.pop('revival_total_xp')
    return digest(encoded(value))
def known_profile(path,profile):
    # ProfileStore intentionally tolerates old optional fields. Simulation must
    # not silently discard an unknown field when saving a rewarded wallet.
    raw=json.loads(path.read_text())
    if type(raw) is not dict or set(raw)-set(asdict(profile)):
        raise ValueError('Unknown profile fields; simulation wallet rewrite refused')
def profile_bytes(profile):
    # Match ProfileStore's established serialization, without changing it.
    value=asdict(profile)
    if not profile.fifa_points:value.pop('fifa_points')
    for key in ('club_name','division_offline','favorite_team_id','revival_total_xp','club_abbreviation',
                'favorite_country_id','favorite_player_id'):
        if value[key] is None:value.pop(key)
    return encoded(value)
def durable_json(path,value):
    if path.is_symlink():raise ValueError('Refusing symlink output')
    fd,name=tempfile.mkstemp(prefix=path.name+'.',suffix='.new',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:out.write(encoded(value));out.flush();os.fsync(out.fileno())
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if os.path.exists(name):os.unlink(name)
def safe_path(account):
    path=Path(account).resolve()
    if path==REAL.resolve() or ROOT/'server/data' in path.parents:
        raise ValueError('Simulation cannot select normal account data')
    if not (ROOT/'reports' in path.parents or Path('/tmp') in path.parents):
        raise ValueError('Use a disposable account under reports/ or /tmp/')
    return path
def backend_uses(account):
    # Refuse sharing this wallet with any ordinary game backend process.
    for proc in Path('/proc').glob('[0-9]*/cmdline'):
        try:args=[x.decode() for x in proc.read_bytes().split(b'\0') if x]
        except (OSError,UnicodeError):continue
        if not any(Path(arg).name=='reachability.py' for arg in args):continue
        for option in ('--profile-state','--football-state','--revival-pack-state','--offline-seasons-state'):
            if option in args:
                index=max(i for i,arg in enumerate(args) if arg==option)
                if Path(args[index+1]).resolve().parent==account:return True
    return False

def provision(account,archive,*,enabled=False,seed_current=False,division=10,test_match_coins=0,season_rewards=False):
    if enabled is not True:raise ValueError('Simulation disabled; explicit enable required')
    target=safe_path(account);source=Path(archive).resolve()
    if target.exists() or source==target or source in target.parents:raise ValueError('Use a new separate account directory')
    if type(seed_current) is not bool or type(season_rewards) is not bool:raise ValueError('Invalid simulation options')
    integer(division,1,10);integer(test_match_coins,0,100000)
    manifest=json.loads((source/'.lab-snapshot.json').read_text())
    required={'profile.json','football.json','seasons.json','definition.json','packs.json','purchases.json'}
    if not required<=manifest['sha256'].keys():raise ValueError('Incomplete archived account')
    for name,expected in manifest['sha256'].items():
        if Path(name).name!=name or digest((source/name).read_bytes())!=expected:raise ValueError('Archive hash mismatch')
    policy=load_policy();profile=ProfileStore(source/'profile.json').load()
    known_profile(source/'profile.json',profile)
    if policy.version!='offline_seasons_console_fifa16_v2' or profile.persona_id!=1:raise ValueError('Unsupported policy/persona')
    initial={'division':division,'played':0,'points':0,'origin':'fresh_backend_simulation'}
    if seed_current:
        current=SeasonStore(source/'seasons.json',load_definition(source/'definition.json')).load()
        if current is None:raise ValueError('No stock progress to reference')
        initial={'division':current.division_index,'played':current.round_number-1,'points':current.user_points,
                 'origin':'captured_stock_aggregate_reference','stock_season_id':current.season_id,
                 'stock_blob_sha256':digest(bytes.fromhex(current.client_state_hex))}
        if initial['played']==10:raise ValueError('Importing completed stock seasons is unproved')
    policy.for_division(initial['division']).evaluate(initial['played'],initial['points'])
    shutil.copytree(source,target)
    if backend_uses(target):raise ValueError('Account selected by a normal game backend')
    account_id=str(uuid.uuid4())
    marker={'schema':1,'classification':'isolated_backend_simulation','account_path':str(target),
            'account_id':account_id,'persona_id':1,'archive':str(source),'baseline_sha256':manifest['sha256'],
            'policy_sha256':digest(POLICY.read_bytes()),'policy_version':policy.version,
            'profile_fields_sha256':profile_fields(profile),'initial':initial,
            'initial_credits':profile.credits,'test_match_coins':test_match_coins,'season_rewards':season_rewards}
    (target/POLICY_COPY).write_bytes(POLICY.read_bytes())
    durable_json(target/JOURNAL,{'schema':1,'classification':'backend_simulation_only','account_id':account_id,
                               'persona_id':1,'policy_version':policy.version,'committed':[]})
    # Enabling marker is written last; incomplete provisioning fails closed.
    durable_json(target/MARKER,marker)
    return SimulationStore(target,enabled=True).inspect()

class SimulationStore:
    def __init__(self,account,*,enabled=False):
        if enabled is not True:raise ValueError('Simulation disabled; explicit enable required')
        self.account=safe_path(account);self.path=self.account/JOURNAL
        self.profile=ProfileStore(self.account/'profile.json')
        self._guard()

    def _guard(self):
        if backend_uses(self.account):raise ValueError('Simulation account is attached to a normal game backend')
        for path in self.account.glob('*.json'):
            if path.is_symlink() or path.resolve().parent!=self.account:raise ValueError('Account contains aliased state')
            real=REAL/path.name
            if real.exists() and os.path.samefile(path,real):raise ValueError('Account hardlinks real state')
        marker=json.loads((self.account/MARKER).read_text())
        required={'schema','classification','account_path','account_id','persona_id','archive','baseline_sha256',
                  'policy_sha256','policy_version','profile_fields_sha256','initial','initial_credits','test_match_coins','season_rewards'}
        if (set(marker)!=required or type(marker['schema']) is not int or marker['schema']!=1 or
            marker['classification']!='isolated_backend_simulation' or marker['account_path']!=str(self.account) or
            type(marker['persona_id']) is not int or marker['persona_id']!=1):raise ValueError('Invalid isolation marker')
        uuid.UUID(marker['account_id']);integer(marker['test_match_coins'],0,100000);validate_credits(marker['initial_credits'])
        if type(marker['season_rewards']) is not bool:raise ValueError('Invalid reward activation')
        if digest((self.account/POLICY_COPY).read_bytes())!=marker['policy_sha256']:raise ValueError('Simulation policy changed')
        self.policy=load_policy(self.account/POLICY_COPY)
        if self.policy.version!=marker['policy_version'] or self.policy.version!='offline_seasons_console_fifa16_v2':raise ValueError('Policy version mismatch')
        for name,expected in marker['baseline_sha256'].items():
            if Path(name).name!=name:raise ValueError('Invalid baseline filename')
            if name!='profile.json' and digest((self.account/name).read_bytes())!=expected:raise ValueError('Stock state changed: '+name)
        profile=self.profile.load()
        known_profile(self.profile.path,profile)
        if profile.persona_id!=1 or profile_fields(profile)!=marker['profile_fields_sha256']:raise ValueError('Profile identity/unrelated fields changed')
        initial=marker['initial'];self.policy.for_division(initial['division']).evaluate(initial['played'],initial['points'])
        if initial['played']>=10:raise ValueError('Invalid initial progress')
        self.marker=marker

    @contextmanager
    def _locked(self):
        self._guard()
        fd=os.open(self.account/'.simulation.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX)
            with self.profile.transaction():
                self._guard();yield
        finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)

    def _id(self,label):return str(uuid.uuid5(uuid.UUID(self.marker['account_id']),label))
    def _new_season(self,sequence,division,played=0,points=0):
        return {'season_instance_id':self._id('season:'+str(sequence)),'sequence':sequence,'division':division,
                'played':played,'points':points,'fixtures':[],'completion':None}
    def _initial(self):
        seed=self.marker['initial'];return [self._new_season(1,seed['division'],seed['played'],seed['points'])]

    def _request(self,request):
        if type(request) is not dict:raise ValueError('Invalid request')
        identity(request.get('request_id'))
        if type(request.get('season_instance_id')) is not str:raise ValueError('Expected issued season ID')
        if request.get('action')=='next_season':
            if set(request)!={'action','request_id','season_instance_id'}:raise ValueError('Invalid next-season request')
        elif request.get('action')=='fixtures':
            if set(request)!={'action','request_id','season_instance_id','fixture_index','results'}:raise ValueError('Invalid fixture request')
            integer(request['fixture_index'],1,10)
            if type(request['results']) is not list or not 1<=len(request['results'])<=10:raise ValueError('Invalid result sequence')
            for result in request['results']:
                if type(result) is not dict or set(result)!={'result','score'} or result['result'] not in ('W','D','L'):raise ValueError('Invalid W/D/L result')
                score=result['score']
                if type(score) is not list or len(score)!=2:raise ValueError('Two score integers required')
                home,away=(integer(v,0,99) for v in score)
                expected='W' if home>away else 'D' if home==away else 'L'
                if expected!=result['result']:raise ValueError('Result/score conflict')
        else:raise ValueError('Unsupported simulation action')
        return copy.deepcopy(request)

    def _plan(self,request,seasons,credits,before_hash,status,sequence):
        request=self._request(request);seasons=copy.deepcopy(seasons);current=seasons[-1]
        if current['season_instance_id']!=request['season_instance_id']:raise ValueError('Stale or unknown season instance')
        txid=self._id('transaction:'+request['request_id']);fixtures=[];rewards=[]
        if request['action']=='next_season':
            if current['completion'] is None:raise ValueError('Season is not complete')
            seasons.append(self._new_season(len(seasons)+1,current['completion']['proposed_next_division']))
            current=seasons[-1]
        else:
            if current['completion'] is not None or request['fixture_index']!=current['played']+1:raise ValueError('Fixture consumed or out of order')
            if len(request['results'])>10-current['played']:raise ValueError('Too many fixtures')
            for result in request['results']:
                index=current['played']+1;fid=self._id('fixture:'+current['season_instance_id']+':'+str(index))
                fixture={'receipt_id':fid,'transaction_id':txid,'account_id':self.marker['account_id'],'persona_id':1,
                         'season_instance_id':current['season_instance_id'],'fixture_index':index,'result':result['result'],
                         'score':result['score'],'points':POINTS[result['result']],
                         'policy_version':self.policy.version,'classification':'server_simulated','status':status}
                current['played'],current['points']=advance(current['played'],current['points'],result['result'])
                current['fixtures'].append(fixture)
                fixtures.append(fixture)
                rewards.append({'receipt_id':self._id('fixture-coins:'+fid),'source_receipt_id':fid,
                                'season_instance_id':current['season_instance_id'],'fixture_index':index,
                                'kind':'simulated_match_coins','amount':self.marker['test_match_coins'],
                                'amount_classification':'explicit_test_only','status':status})
            decision=self.policy.for_division(current['division']).evaluate(current['played'],current['points'])
            if decision['complete']:
                current['completion']=decision
                rewards.append({'receipt_id':self._id('season-coins:'+current['season_instance_id']),
                    'source_receipt_id':fixtures[-1]['receipt_id'],'season_instance_id':current['season_instance_id'],
                    'fixture_index':10,'kind':'simulated_season_coins',
                    'amount':decision['proposed_season_coins'] if self.marker['season_rewards'] else 0,
                    'amount_classification':'console_reference_simulation_only','status':status})
        for reward in rewards:
            reward.update(account_id=self.marker['account_id'],persona_id=1,transaction_id=txid,
                          policy_version=self.policy.version,classification='simulation_reward_only')
        after=validate_credits(credits+sum(r['amount'] for r in rewards))
        after_hash=before_hash if after==credits else digest(profile_bytes(replace(self.profile.load(),credits=after)))
        record={'transaction_id':txid,'request':request,'sequence':sequence,'account_id':self.marker['account_id'],
                'persona_id':1,'policy_version':self.policy.version,'status':status,'fixtures':fixtures,'rewards':rewards,
                'credits_before':credits,'credits_after':after,'profile_before_sha256':before_hash,'profile_after_sha256':after_hash,
                'season_after':{k:v for k,v in current.items() if k!='fixtures'}}
        return record,seasons

    def _load(self):
        value=json.loads(self.path.read_text())
        keys={'schema','classification','account_id','persona_id','policy_version','committed'}
        if (not keys<=set(value) or set(value)-keys-{'prepared'} or type(value['schema']) is not int or value['schema']!=1 or
            value['classification']!='backend_simulation_only' or value['account_id']!=self.marker['account_id'] or
            type(value['persona_id']) is not int or value['persona_id']!=1 or value['policy_version']!=self.policy.version or
            type(value['committed']) is not list):raise ValueError('Invalid simulation journal')
        seasons=self._initial();credits=self.marker['initial_credits'];before_hash=self.marker['baseline_sha256']['profile.json'];ids=set()
        for seq,record in enumerate(value['committed'],1):
            if type(record) is not dict:raise ValueError('Invalid receipt')
            expected,seasons=self._plan(record['request'],seasons,credits,before_hash,'committed',seq)
            if record!=expected or record['request']['request_id'] in ids:raise ValueError('Invalid/repeated committed receipt')
            ids.add(record['request']['request_id']);credits=record['credits_after'];before_hash=record['profile_after_sha256']
        if 'prepared' in value:
            record=value['prepared'];expected,_=self._plan(record['request'],seasons,credits,before_hash,'prepared',len(ids)+1)
            if record!=expected or record['request']['request_id'] in ids:raise ValueError('Invalid prepared receipt')
        return value,seasons,credits,before_hash

    def _save(self,value):durable_json(self.path,value)
    def _settled(self,before_hash):
        if digest(self.profile.path.read_bytes())!=before_hash:raise ValueError('Wallet diverged; refusing overwrite')
    def _complete(self,value,seasons,credits,before_hash):
        prepared=value['prepared'];actual=digest(self.profile.path.read_bytes())
        if actual not in (prepared['profile_before_sha256'],prepared['profile_after_sha256']):raise ValueError('Recovery wallet conflict')
        if actual!=prepared['profile_after_sha256']:
            self.profile.save(replace(self.profile.load(),credits=prepared['credits_after']))
        self._settled(prepared['profile_after_sha256'])
        committed,_=self._plan(prepared['request'],seasons,credits,before_hash,'committed',prepared['sequence'])
        value['committed'].append(committed);value.pop('prepared');self._save(value)
        return copy.deepcopy(committed)

    @account_locked
    def commit(self,request):
        request=self._request(request)
        with self._locked():
            value,seasons,credits,before_hash=self._load()
            if 'prepared' in value:
                if request!=value['prepared']['request']:raise ValueError('Recover pending transaction before another request')
                return self._complete(value,seasons,credits,before_hash)
            self._settled(before_hash)
            prior=next((r for r in value['committed'] if r['request']['request_id']==request['request_id']),None)
            if prior:
                if prior['request']!=request:raise ValueError('Retry request conflicts with original receipt')
                return copy.deepcopy(prior)
            prepared,_=self._plan(request,seasons,credits,before_hash,'prepared',len(value['committed'])+1)
            value['prepared']=prepared;self._save(value)
            return self._complete(value,seasons,credits,before_hash)

    @account_locked
    def recover(self):
        with self._locked():
            value,seasons,credits,before_hash=self._load()
            if 'prepared' in value:return self._complete(value,seasons,credits,before_hash)
            self._settled(before_hash);return {'status':'settled','transactions':len(value['committed'])}

    @account_locked
    def preview(self,request):
        with self._locked():
            value,seasons,credits,before_hash=self._load()
            if 'prepared' in value:raise ValueError('Recovery required before preview')
            self._settled(before_hash);request=self._request(request)
            prior=next((r for r in value['committed'] if r['request']['request_id']==request['request_id']),None)
            if prior:
                if prior['request']!=request:raise ValueError('Retry request conflict')
                return copy.deepcopy(prior)
            return self._plan(request,seasons,credits,before_hash,'preview',len(value['committed'])+1)[0]

    @account_locked
    def inspect(self):
        with self._locked():
            value,seasons,credits,before_hash=self._load()
            if 'prepared' not in value:self._settled(before_hash)
            current=seasons[-1]
            return {'classification':'backend_simulation_only','account_id':self.marker['account_id'],'persona_id':1,
                    'policy_version':self.policy.version,'initial_origin':self.marker['initial'],
                    'seasons':seasons,'current':current,'decision':self.policy.for_division(current['division']).evaluate(current['played'],current['points']),
                    'committed_credits':credits,'observed_profile_credits':self.profile.load().credits,
                    'pending':copy.deepcopy(value.get('prepared')),'transactions':copy.deepcopy(value['committed']),
                    'next_fixture_index':current['played']+1 if current['played']<10 else None,
                    'remaining_fixture_indices':list(range(current['played']+1,11)),
                    'stock_state_projected':False}

    def fixture_request(self,request_id,results,*,season_instance_id=None,fixture_index=None):
        view=self.inspect();prior=next((r for r in view['transactions']+[view['pending']] if r and r['request']['request_id']==request_id),None)
        current=view['current'];old=prior['request'] if prior else {}
        return {'action':'fixtures','request_id':request_id,
                'season_instance_id':season_instance_id if season_instance_id is not None else old.get('season_instance_id',current['season_instance_id']),
                'fixture_index':fixture_index if fixture_index is not None else old.get('fixture_index',current['played']+1),'results':results}

    def next_season_request(self,request_id,season_instance_id=None):
        view=self.inspect();prior=next((r for r in view['transactions']+[view['pending']] if r and r['request']['request_id']==request_id),None)
        return {'action':'next_season','request_id':request_id,'season_instance_id':season_instance_id if season_instance_id is not None else
                (prior['request']['season_instance_id'] if prior else view['current']['season_instance_id'])}

    def reward(self,receipt_id):
        view=self.inspect()
        if view['pending'] is not None:raise ValueError('Recovery required before reward lookup')
        matches=[r for tx in view['transactions'] for r in tx['rewards'] if r['receipt_id']==receipt_id]
        if len(matches)!=1:raise ValueError('No committed reward receipt')
        return copy.deepcopy(matches[0])

def result(value,score=None):
    names={'win':'W','draw':'D','loss':'L','W':'W','D':'D','L':'L'}
    if value not in names:raise ValueError('Expected win/draw/loss or W/D/L')
    code=names[value]
    return {'result':code,'score':list(score) if score is not None else {'W':[1,0],'D':[0,0],'L':[0,1]}[code]}
