import hashlib
from dataclasses import dataclass
from typing import Protocol
class AnnotationSink(Protocol):
    def append(self,case:dict)->None: ...
@dataclass(frozen=True)
class OnlineEvalDecision:
    trace_checks:bool; automated_grader:bool; semantic_grader:bool; human_annotation:bool
def sampling_decision(run_id:str,*,failed:bool=False,confidence:float=1.0)->OnlineEvalDecision:
    bucket=int(hashlib.sha256(run_id.encode()).hexdigest()[:8],16)%100
    return OnlineEvalDecision(True,bucket<10,bucket<3,failed or confidence<.55)
def capture_regression_case(*,sink:AnnotationSink,run_id:str,input_payload:dict,output_payload:dict,trace_id:str,failed:bool,confidence:float)->OnlineEvalDecision:
    decision=sampling_decision(run_id,failed=failed,confidence=confidence)
    if decision.human_annotation:sink.append({"case_id":f"production-{run_id}","input":input_payload,"observed_output":output_payload,"metadata":{"source":"production_failure","trace_id":trace_id,"requires_human_annotation":True}})
    return decision
