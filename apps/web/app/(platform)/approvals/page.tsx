"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { gatewayFetch } from "../../../lib/api/gateway-client";
import { ApprovalListSchema, type Approval } from "../../../lib/schemas/approvals";
import { useFrontendSession } from "../../../providers/session-provider";
import { Button } from "../../../components/ui/button";
import { StatePanel } from "../../../components/ui/state-panel";

export default function ApprovalsPage(){
 const session=useFrontendSession(); const client=useQueryClient();
 const queue=useQuery({queryKey:["approvals",session.tenantId],queryFn:()=>gatewayFetch("/api/v1/approvals",session,{},ApprovalListSchema)});
 const decision=useMutation({mutationFn:({item,decision}:{item:Approval;decision:"approve"|"reject"|"request_changes"})=>gatewayFetch(`/api/v1/approvals/${encodeURIComponent(item.approval_id)}/decision`,session,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({decision,comment:decision==="reject"?"Rejected after reviewer evidence check":decision==="request_changes"?"Additional evidence required":"Reviewed evidence and approved",expected_version:item.version})}),onSuccess:()=>client.invalidateQueries({queryKey:["approvals",session.tenantId]})});
 if(queue.isLoading)return <div className="page"><StatePanel title="Loading review queue" description="Retrieving current high-risk approvals…"/></div>;
 if(queue.error)return <div className="page"><StatePanel role="alert" title="Approval queue unavailable" description={queue.error.message}/></div>;
 const items=queue.data??[];
 return <div className="page approvalPage"><section className="hero"><p className="eyebrow">Human-in-the-loop approval</p><h1>High-risk review queue</h1><p className="lede">Every production-risk decision is durable, versioned, signed, expiring, and concurrency-safe before workflow resume.</p>{decision.error&&<p className="error" role="alert">{decision.error.message}</p>}</section><section className="approvalQueue">{items.length===0?<StatePanel title="No approvals waiting" description="The queue is clear for your reviewer identity and roles."/>:items.map(item=><article className="card approvalCard" key={item.approval_id}><div className="approvalHeader"><div><p className="eyebrow">{item.risk} · risk {item.risk_score}</p><h2>{item.evidence_summary.title}</h2></div><span>{item.status}</span></div><p>{item.evidence_summary.summary}</p><dl><dt>Action</dt><dd>{item.action_type}</dd><dt>Expires</dt><dd>{new Date(item.expires_at).toLocaleString()}</dd><dt>Version</dt><dd>{item.version}</dd><dt>Evidence</dt><dd>{item.evidence_summary.evidence_ids.join(", ")||"—"}</dd><dt>Citations</dt><dd>{item.evidence_summary.citation_ids.join(", ")||"—"}</dd></dl><div className="approvalActions"><Button disabled={decision.isPending} onClick={()=>decision.mutate({item,decision:"approve"})}>Approve</Button><Button variant="outline" disabled={decision.isPending} onClick={()=>decision.mutate({item,decision:"request_changes"})}>Request changes</Button><Button variant="danger" disabled={decision.isPending} onClick={()=>decision.mutate({item,decision:"reject"})}>Reject</Button></div></article>)}</section></div>;
}
