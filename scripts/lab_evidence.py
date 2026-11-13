#!/usr/bin/env python3
"""Evidence mechanics only: no ADB, server control, account writes or grants.

Snapshot quiescent JSON stores, compare bytes, hash chosen sources, discover the
next unused capture, or execute an explicit argv test plan with durable results.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

SNAPSHOT_MANIFEST = '.lab-snapshot.json'

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def digest(data):
    return hashlib.sha256(data).hexdigest()

def file_digest(path):
    hasher=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):hasher.update(chunk)
    return hasher.hexdigest()

def json_files(folder):
    return {p.name:p.read_bytes() for p in sorted(Path(folder).glob('*.json'))
            if p.name != SNAPSHOT_MANIFEST and p.is_file()}

def new_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:
        json.dump(value,f,indent=2);f.write('\n')

def snapshot(source, output):
    source=Path(source).resolve();output=Path(output).resolve()
    if not source.is_dir() or output==source or source in output.parents:
        raise ValueError('Use an existing account directory and a separate archive')
    if output.exists():raise FileExistsError(output)
    files=json_files(source)
    if not files:raise ValueError('No account JSON files found')
    for raw in files.values():json.loads(raw)
    if files!=json_files(source):raise ValueError('Stores changed during snapshot; quiesce writers and retry')
    output.mkdir(parents=True)
    for name,raw in files.items():(output/name).write_bytes(raw)
    value={'source':str(source),'utc':now(),'sha256':{name:digest(raw) for name,raw in files.items()},
           'consistency':'Two identical reads; cross-store coherence requires quiescent writers.'}
    new_json(output/SNAPSHOT_MANIFEST,value)
    return value

def compare(before, after):
    a=json_files(before);b=json_files(after)
    if not a or not b:raise ValueError('Both directories must contain JSON state')
    return {'identical':a==b,'added':sorted(b.keys()-a.keys()),'removed':sorted(a.keys()-b.keys()),
            'changed':sorted(k for k in a.keys()&b.keys() if a[k]!=b[k])}

def hashes(paths):
    result={}
    for path in paths:
        path=Path(path)
        if not path.exists():raise FileNotFoundError(path)
        files=sorted(p for p in path.rglob('*') if p.is_file()) if path.is_dir() else [path]
        for file in files:result[str(file)]=file_digest(file)
    return result

def next_capture(root):
    # Match capture.py's reservation rule, including a numeric file collision.
    numbers=[int(p.name[4:]) for p in Path(root).glob('run-*') if p.name[4:].isdigit()]
    return 'run-'+str(max(numbers,default=0)+1)

def replace_json(path, value):
    path=Path(path)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix=path.name+'.')
    try:
        with os.fdopen(fd,'w') as f:
            json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def verify(commands, output, cwd, timeout):
    if not commands or any(not isinstance(c,list) or not c or
        any(not isinstance(v,str) or not v for v in c) for c in commands):
        raise ValueError('Test plan must be a nonempty JSON array of argv arrays')
    cwd=Path(cwd).resolve()
    if not cwd.is_dir():raise ValueError('Verification cwd does not exist')
    results=[];new_json(output,results)
    for command in commands:
        row={'command':command,'cwd':str(cwd),'started_utc':now(),'exit':None}
        results.append(row);replace_json(output,results)
        try:
            p=subprocess.run(command,cwd=cwd,capture_output=True,text=True,errors='replace',timeout=timeout)
            row.update(exit=p.returncode,stdout=p.stdout,stderr=p.stderr,output=p.stdout+p.stderr)
        except subprocess.TimeoutExpired as e:
            def text(v):return v.decode(errors='replace') if isinstance(v,bytes) else v or ''
            row.update(exit=124,timeout_seconds=timeout,output=text(e.stdout)+text(e.stderr))
        except OSError as e:row.update(exit=127,output=str(e))
        row['finished_utc']=now();replace_json(output,results)
    return results

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    s=sub.add_parser('snapshot');s.add_argument('--source',type=Path,required=True);s.add_argument('--output',type=Path,required=True)
    s=sub.add_parser('compare');s.add_argument('before',type=Path);s.add_argument('after',type=Path);s.add_argument('--output',type=Path)
    s=sub.add_parser('hashes');s.add_argument('--output',type=Path,required=True);s.add_argument('paths',type=Path,nargs='+')
    s=sub.add_parser('next-capture');s.add_argument('--captures',type=Path,default=Path(__file__).resolve().parents[1]/'captures')
    s=sub.add_parser('verify');s.add_argument('--commands',type=Path,required=True);s.add_argument('--output',type=Path,required=True)
    s.add_argument('--cwd',type=Path,default=Path(__file__).resolve().parents[1]);s.add_argument('--timeout',type=float,default=120)
    a=p.parse_args()
    try:
        if a.action=='snapshot':value=snapshot(a.source,a.output)
        elif a.action=='compare':
            value=compare(a.before,a.after)
            if a.output:new_json(a.output,value)
            print(json.dumps(value,indent=2));return 0 if value['identical'] else 1
        elif a.action=='hashes':value=hashes(a.paths);new_json(a.output,value)
        elif a.action=='next-capture':print(next_capture(a.captures));return 0
        else:
            if a.timeout<=0:raise ValueError('Timeout must be positive')
            value=verify(json.loads(a.commands.read_text()),a.output,a.cwd,a.timeout)
            print(json.dumps({'commands':len(value),'failed':sum(r['exit']!=0 for r in value)}))
            return 1 if any(r['exit']!=0 for r in value) else 0
        print(json.dumps(value,indent=2));return 0
    except (ValueError,OSError) as e:p.exit(2,str(e)+'\n')

if __name__=='__main__':raise SystemExit(main())
