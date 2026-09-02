from __future__ import annotations
import json
from typing import Any, Iterable
ROUTING_CONTEXT_KEYS=("service","environment","incident_id","repository","pull_request","evidence_modalities","requested_action","graph_version")
PLANNING_CONTEXT_KEYS=(*ROUTING_CONTEXT_KEYS,"supervisor_decision","constraints","available_evidence")
def project_context(context:dict[str,Any],*,keys:Iterable[str],max_bytes:int=6000)->dict[str,Any]:
    """Expose only task-relevant context under a hard serialized prompt boundary."""
    projected={key:context[key] for key in keys if key in context and context[key] is not None}
    if len(json.dumps(projected,sort_keys=True,default=str,separators=(",",":")).encode())<=max_bytes:return projected
    return {key:value for key,value in projected.items() if isinstance(value,(str,int,float,bool)) and len(str(value))<=512}
