"""Opt-in current-login squad editing policy; no ownership or second journal.

The stock UI reuses numeric slots without an operation nonce. User-authorized
local policy treats requests from the active login as sequential current intent.
Identical retries are idempotent until an intervening edit/delete/recreation;
closed login requests are refused by the existing native session boundary.
"""
import json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MARKER='squad-slot-authority.json'
VERSION='current_session_squad_authority_v1'
ACCOUNT=POLICY=None

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def configure(account=None):
 global ACCOUNT,POLICY
 ACCOUNT=POLICY=None
 if account is None:return
 account=Path(account).resolve();marker=account/MARKER
 from .fresh_account_runtime import selected as fresh_selected
 if fresh_selected(account):
  from .native_pack_sessions import selected as sessions_selected
  if not sessions_selected(account):
   raise ValueError('Fresh squad authority requires checked native sessions')
  ACCOUNT, POLICY = account, {'fresh_account': True}
  return
 if not marker.exists():return
 v=json.loads(marker.read_bytes())
 if (set(v)!={'version','account','archive','manifest_sha256','phase','certificate','certificate_sha256'} or
     v['version']!=VERSION or v['account']!=str(account) or v['phase'] not in ('candidate','enabled')):raise ValueError('Invalid squad authority policy')
 from . import native_pack_sessions as sessions
 if not sessions.selected(account):raise ValueError('Squad authority requires checked original native sessions')
 if v['phase']=='candidate':
  if ROOT/'reports' not in account.parents or account.name!='isolated-account' or not (account/'.lab-snapshot.json').is_file() or v['certificate'] is not None or v['certificate_sha256'] is not None:raise ValueError('Uncertified squad authority is isolated-only')
 else:
  from .store_release import REAL
  if account!=REAL:raise ValueError('Squad authority release owner differs')
  cert=Path(v['certificate']).resolve()
  if ROOT/'reports/squad-slot-renewal' not in cert.parents or sha(cert)!=v['certificate_sha256']:raise ValueError('Squad authority certificate changed')
  proof=json.loads(cert.read_bytes())
  if proof.get('status')!='STOCK_VERIFIED_CURRENT_SESSION_SQUADS' or any(proof.get(k) is not True for k in
      ('create_delete_recreate','sequential_edit','duplicate_retry','old_session_refusal','restart_verified','ownership_preserved','deleted_selection_recovery')):raise ValueError('Squad authority certificate incomplete')
 origin=Path(v['archive']).resolve()
 if ROOT/'reports' not in origin.parents or origin==account or account in origin.parents or sha(origin/'.lab-snapshot.json')!=v['manifest_sha256']:raise ValueError('Separate squad authority archive required')
 files=json.loads((origin/'.lab-snapshot.json').read_bytes())['sha256']
 if not {'football.json','profile.json'}<=files.keys():raise ValueError('Incomplete squad authority archive')
 for n,h in files.items():
  p=origin/n
  if Path(n).name!=n or p.is_symlink() or sha(p)!=h:raise ValueError('Squad authority archive changed')
 old=json.loads((origin/'profile.json').read_bytes());current=json.loads((account/'profile.json').read_bytes())
 if any(old[k]!=current[k] for k in ('persona_id','identity_pid','user_id')):raise ValueError('Squad authority account changed')
 ACCOUNT,POLICY=account,{**v,'marker_sha256':sha(marker)}

def session_id(store,headers):
 if ACCOUNT is None:return None
 if store.path.resolve().parent!=ACCOUNT:raise ValueError('Squad authority selector differs')
 if POLICY.get('fresh_account'):
  from .fresh_account_runtime import selected as fresh_selected
  if not fresh_selected(ACCOUNT):
   raise ValueError('Fresh squad authority changed')
 elif sha(ACCOUNT/MARKER)!=POLICY['marker_sha256']:raise ValueError('Squad authority changed during runtime')
 from . import native_pack_sessions as sessions
 if not sessions.selected(ACCOUNT) or sessions.is_stale(headers):raise ValueError('Current authenticated squad session required')
 e=sessions.current();actual=headers.get(sessions.RAW_SID)
 if e is None or actual!=e['sid'].encode():raise ValueError('Checked original squad SID required')
 return e['sid']
