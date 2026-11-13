"""Only Squad-triggered StaffStats; run129 failure is fatal to TeamManagement.

Factory0230f124 zeros22 bonus bytes, parser0230f41c accepts omitted optional
bonus list, callback01a5ffb8 installs defaults. No staff items exist locally.
This response is a transient neutral initialization, not broad club statistics.
"""
from .identity import json_response
PATH='/ut/game/fifaworldmobile/club/stats/staff'
def response_for(method,target,headers,body):
 if (method=='GET' and target==PATH and headers.get(b'host')==b'10.0.2.2:18081'
     and headers.get(b'x-ut-sid')==b'fifa16-local-sid' and not body
     and headers.get(b'content-length',b'0')==b'0'):return json_response({})
 return None
