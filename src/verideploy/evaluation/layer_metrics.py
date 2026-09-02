from dataclasses import asdict, dataclass
from statistics import fmean

@dataclass(frozen=True)
class AILayerObservation:
    supervisor_routing_accuracy:float; planner_dag_validity:float; tool_selection_accuracy:float
    rag_recall_at_k:float; rag_mrr:float; rag_ndcg:float; reranker_ndcg:float
    context_precision:float; context_recall:float; citation_accuracy:float; rca_root_cause_accuracy:float
    critic_precision:float; critic_recall:float; unsupported_claim_rate:float; human_escalation_precision:float
    graph_completion_rate:float; retries:int; input_tokens:int; output_tokens:int; latency_ms:float; cost_usd:float; successful:bool

def summarize_ai_layers(rows:list[AILayerObservation])->dict:
    """Expose every layer separately; no opaque aggregate score."""
    if not rows:return {"case_count":0}
    result={"case_count":len(rows)}
    for name in asdict(rows[0]):
        if name!="successful":result[name]=fmean(float(getattr(row,name)) for row in rows)
    successful=[row for row in rows if row.successful];result["successful_investigations"]=len(successful)
    for name in ("retries","input_tokens","output_tokens","latency_ms","cost_usd"):
        result[f"{name}_per_successful_investigation"]=fmean(float(getattr(x,name)) for x in successful) if successful else None
    return result
