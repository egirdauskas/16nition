"""Read complete collector records while its final JSONL line may be in flight."""
import json
from pathlib import Path

def read_events(path,offset=0):
    with Path(path).open('rb') as stream:
        stream.seek(offset)
        data=stream.read()
    # Only a newline commits a collector record. A malformed complete line
    # remains an error; do not suppress evidence corruption or schema failures.
    complete=data[:data.rfind(b'\n')+1]
    return [json.loads(line) for line in complete.splitlines() if line.strip()]
