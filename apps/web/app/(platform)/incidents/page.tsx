"use client";

import { FormEvent,useCallback,useEffect,useMemo,useRef,useState } from "react";
import { useQuery,useQueryClient } from "@tanstack/react-query";
import { AlertTriangle,CheckCircle2,Clock3,GitBranch,Link2,RefreshCw,Square,Wifi,WifiOff,XCircle } from "lucide-react";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card,CardContent,CardHeader } from "../../../components/ui/card";
import { gatewayFetch,gatewayRequest } from "../../../lib/api/gateway-client";
import { InvestigationEventSchema,InvestigationProjectionSchema,isContiguous,reduceInvestigationEvent,type InvestigationEvent,type InvestigationProjection } from "../../../lib/investigations/convergence";
import { useFrontendSession } from "../../../providers/session-provider";

type QueuedInvestigation={investigation_id:string;correlation_id:string;status:string};
type ConnectionState="idle"|"connecting"|"live"|"replaying"|"reconciling"|"disconnected";
const TERMINAL=new Set(["CANCELLED","COMPLETED","FAILED"]);

function statusTone(status:string):"default"|"success"|"warning"|"danger"{if(status==="COMPLETED")return"success";if(status==="FAILED"||status==="CANCELLED")return"danger";if(status==="CANCELLING")return"warning";return"default"}
function percentage(value:number){return `${Math.round(value*100)}%`}

export default function IncidentInvestigationPage(){
  const session=useFrontendSession();
  const queryClient=useQueryClient();
  const[selectedId,setSelectedId]=useState<string|null>(null);
  const[connection,setConnection]=useState<ConnectionState>("idle");
  const[error,setError]=useState("");
  const[busy,setBusy]=useState(false);
  const[reconcileCount,setReconcileCount]=useState(0);
  const abortRef=useRef<AbortController|null>(null);
  const retryRef=useRef(0);

  const viewQuery=useQuery({queryKey:["investigation-view",selectedId],enabled:Boolean(selectedId),queryFn:()=>gatewayFetch(`/api/v1/investigations/${selectedId}/view`,session,{},InvestigationProjectionSchema),refetchOnWindowFocus:false});
  const view=viewQuery.data??null;

  const setView=useCallback((next:InvestigationProjection)=>{if(!selectedId)return;queryClient.setQueryData(["investigation-view",selectedId],next);},[queryClient,selectedId]);
  const authoritativeRefresh=useCallback(async(id:string)=>{setConnection("reconciling");const authoritative=await gatewayFetch(`/api/v1/investigations/${id}/view`,session,{},InvestigationProjectionSchema);queryClient.setQueryData(["investigation-view",id],authoritative);setReconcileCount(value=>value+1);return authoritative;},[queryClient,session]);
  const replayFrom=useCallback(async(id:string,after:number,base:InvestigationProjection)=>{setConnection("replaying");const raw=await gatewayFetch<unknown[]>(`/api/v1/investigations/${id}/events?after_sequence=${after}`,session);let next=base;for(const candidate of raw){const parsed=InvestigationEventSchema.safeParse(candidate);if(!parsed.success)continue;if(parsed.data.sequence_number<=next.last_sequence_number)continue;if(!isContiguous(next,parsed.data))break;next=reduceInvestigationEvent(next,parsed.data);}queryClient.setQueryData(["investigation-view",id],next);return next;},[queryClient,session]);

  const connect=useCallback(async(id:string)=>{
    abortRef.current?.abort();const controller=new AbortController();abortRef.current=controller;retryRef.current=0;setError("");
    let base=await authoritativeRefresh(id);
    if(TERMINAL.has(base.status)){setConnection("idle");return;}
    while(!controller.signal.aborted&&retryRef.current<5){
      try{
        setConnection("connecting");
        const response=await gatewayRequest(`/api/v1/investigations/${id}/stream`,session,{headers:{"last-event-id":String(base.last_sequence_number),accept:"text/event-stream"},signal:controller.signal});
        if(!response.body)throw new Error("Live investigation stream returned no response body");
        setConnection("live");retryRef.current=0;
        const reader=response.body.getReader(),decoder=new TextDecoder();let buffer="";
        while(!controller.signal.aborted){const{value,done}=await reader.read();if(done)throw new Error("Live investigation stream ended");buffer+=decoder.decode(value,{stream:true});const frames=buffer.split("\n\n");buffer=frames.pop()??"";for(const frame of frames){const dataLines=frame.split("\n").filter(line=>line.startsWith("data: "));for(const line of dataLines){let payload:unknown;try{payload=JSON.parse(line.slice(6));}catch{continue}const candidates=Array.isArray(payload)?payload:[payload];for(const candidate of candidates){const parsed=InvestigationEventSchema.safeParse(candidate);if(!parsed.success)continue;const event:InvestigationEvent=parsed.data;if(event.sequence_number<=base.last_sequence_number)continue;if(!isContiguous(base,event)){base=await replayFrom(id,base.last_sequence_number,base);if(event.sequence_number<=base.last_sequence_number)continue;if(!isContiguous(base,event)){base=await authoritativeRefresh(id);continue;}}base=reduceInvestigationEvent(base,event);queryClient.setQueryData(["investigation-view",id],base);if(TERMINAL.has(base.status)){base=await authoritativeRefresh(id);controller.abort();setConnection("idle");return;}}}}}
      }catch(caught){if(controller.signal.aborted)return;retryRef.current+=1;setConnection("disconnected");setError(caught instanceof Error?caught.message:"Live stream disconnected");try{base=await replayFrom(id,base.last_sequence_number,base);base=await authoritativeRefresh(id);}catch{}if(TERMINAL.has(base.status))return;await new Promise(resolve=>setTimeout(resolve,Math.min(5000,500*2**retryRef.current)));}
    }
  },[authoritativeRefresh,queryClient,replayFrom,session]);

  useEffect(()=>()=>abortRef.current?.abort(),[]);

  async function submit(event:FormEvent<HTMLFormElement>){event.preventDefault();setBusy(true);setError("");abortRef.current?.abort();const form=new FormData(event.currentTarget);try{const queued=await gatewayFetch<QueuedInvestigation>("/api/v1/investigations",session,{method:"POST",headers:{"content-type":"application/json","idempotency-key":crypto.randomUUID()},body:JSON.stringify({query:String(form.get("query")),incident_id:String(form.get("incident_id")||"")||undefined})});setSelectedId(queued.investigation_id);await queryClient.invalidateQueries({queryKey:["investigation-view",queued.investigation_id]});void connect(queued.investigation_id);}catch(caught){setError(caught instanceof Error?caught.message:"Investigation creation failed");}finally{setBusy(false)}}
  async function cancel(){if(!selectedId||!view)return;try{await gatewayFetch(`/api/v1/investigations/${selectedId}/cancel`,session,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({reason:"Cancelled by incident investigator"})});await authoritativeRefresh(selectedId);}catch(caught){setError(caught instanceof Error?caught.message:"Cancellation failed")}}
  async function reconcile(){if(!selectedId||!view)return;try{let next=await replayFrom(selectedId,view.last_sequence_number,view);next=await authoritativeRefresh(selectedId);setView(next);if(!TERMINAL.has(next.status))void connect(selectedId);}catch(caught){setError(caught instanceof Error?caught.message:"Reconciliation failed")}}

  const hypothesisEvidence=useMemo(()=>new Map((view?.evidence_map??[]).map(item=>[item.evidence_id,item])),[view?.evidence_map]);
  return <div className="space-y-6">
    <section className="space-y-2"><p className="eyebrow">Incident Intelligence</p><h1 className="text-3xl font-semibold tracking-tight">Real-Time Incident Investigation</h1><p className="max-w-4xl text-sm text-muted-foreground">Create a durable investigation, follow ordered evidence and hypothesis evolution, inspect RCA alternatives, and recover cleanly from event-stream reconnects.</p></section>
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
      <Card><CardHeader><h2 className="font-semibold">Start investigation</h2></CardHeader><CardContent><form className="space-y-4" onSubmit={submit}><label className="grid gap-2 text-sm font-medium">Incident ID<input className="rounded-lg border bg-background px-3 py-2" name="incident_id" placeholder="INC-2026-0042"/></label><label className="grid gap-2 text-sm font-medium">Investigation question<textarea className="min-h-36 rounded-lg border bg-background px-3 py-2" name="query" required minLength={10} placeholder="Why did checkout latency rise immediately after the release?"/></label><Button className="w-full" disabled={busy}>{busy?"Submitting…":"Start investigation"}</Button></form>{error&&<p className="mt-4 rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800" role="alert">{error}</p>}</CardContent></Card>
      <div className="space-y-6">
        <Card><CardContent className="flex flex-wrap items-center justify-between gap-4 py-4"><div>{view?<><div className="flex items-center gap-2"><Badge variant={statusTone(view.status)}>{view.status}</Badge><span className="text-sm font-medium">{view.incident_id||view.investigation_id}</span></div><p className="mt-1 text-xs text-muted-foreground">Sequence {view.last_sequence_number} · reconciled {reconcileCount}×</p></>:<p className="text-sm text-muted-foreground">No investigation active.</p>}</div><div className="flex items-center gap-2" aria-live="polite">{connection==="live"?<><Wifi className="h-4 w-4"/><span className="text-sm">Live</span></>:connection==="disconnected"?<><WifiOff className="h-4 w-4"/><span className="text-sm">Disconnected</span></>:connection!=="idle"?<><RefreshCw className="h-4 w-4 animate-spin"/><span className="text-sm">{connection}</span></>:null}{view&&<Button variant="outline" onClick={()=>void reconcile()}><RefreshCw className="mr-2 h-4 w-4"/>Reconcile</Button>}{view&&!TERMINAL.has(view.status)&&<Button variant="danger" onClick={()=>void cancel()}><Square className="mr-2 h-4 w-4"/>Cancel</Button>}</div></CardContent></Card>
        {!view&&<Card><CardContent className="py-12 text-center"><Clock3 className="mx-auto h-8 w-8 text-muted-foreground"/><h2 className="mt-3 font-semibold">No active investigation</h2><p className="mt-1 text-sm text-muted-foreground">Create an investigation to populate the live timeline, hypotheses, RCA, and evidence map.</p></CardContent></Card>}
        {view&&<>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2"><Card><CardHeader><h2 className="font-semibold">Root cause analysis</h2></CardHeader><CardContent>{view.root_cause?<div className="space-y-3"><div className="flex items-center gap-2">{view.root_cause.determined?<CheckCircle2 className="h-5 w-5 text-green-600"/>:<AlertTriangle className="h-5 w-5 text-amber-600"/>}<strong>{view.root_cause.determined?"Determined":"Candidate"}</strong><Badge>{percentage(view.root_cause.confidence)}</Badge></div><p>{view.root_cause.summary}</p><p className="text-xs text-muted-foreground">Evidence: {view.root_cause.evidence_ids.join(", ")||"No linked evidence"}</p></div>:<p className="text-sm text-muted-foreground">RCA has not produced a supported root-cause candidate yet.</p>}</CardContent></Card><Card><CardHeader><h2 className="font-semibold">Alternative causes</h2></CardHeader><CardContent>{view.alternatives.length?<ul className="space-y-3">{view.alternatives.map(item=><li className="rounded-lg border p-3" key={`${item.hypothesis_id}-${item.updated_sequence}`}><div className="flex justify-between gap-3"><span>{item.summary}</span><Badge>{percentage(item.confidence)}</Badge></div></li>)}</ul>:<p className="text-sm text-muted-foreground">No alternative causes have been recorded.</p>}</CardContent></Card></div>
          <Card><CardHeader><h2 className="font-semibold">Hypothesis evolution</h2></CardHeader><CardContent>{view.hypotheses.length?<div className="grid grid-cols-1 gap-3 md:grid-cols-2">{view.hypotheses.map(item=><article className="rounded-lg border p-4" key={item.hypothesis_id}><div className="flex items-start justify-between gap-3"><div><p className="font-medium">{item.title}</p><p className="text-xs text-muted-foreground">{item.hypothesis_id} · sequence {item.updated_sequence}</p></div><Badge>{percentage(item.confidence)}</Badge></div><div className="mt-3 flex flex-wrap gap-2 text-xs">{item.supporting_evidence_ids.map(id=><span className="rounded-full bg-green-50 px-2 py-1 text-green-800" key={id}>+ {hypothesisEvidence.get(id)?.label??id}</span>)}{item.disconfirming_evidence_ids.map(id=><span className="rounded-full bg-red-50 px-2 py-1 text-red-800" key={id}>− {hypothesisEvidence.get(id)?.label??id}</span>)}</div></article>)}</div>:<p className="text-sm text-muted-foreground">Hypotheses will appear as investigation agents publish evidence-backed updates.</p>}</CardContent></Card>
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2"><Card><CardHeader><h2 className="font-semibold">Evidence map</h2></CardHeader><CardContent>{view.evidence_map.length?<div className="space-y-3">{view.evidence_map.map(item=><article className="flex items-start gap-3 rounded-lg border p-3" key={item.evidence_id}><Link2 className="mt-0.5 h-4 w-4"/><div><p className="font-medium">{item.label}</p><p className="text-xs text-muted-foreground">{item.evidence_type} → {item.relation}{item.hypothesis_id?` → ${item.hypothesis_id}`:""}</p>{item.citation_id&&<a className="text-xs underline" href={`/citations/${item.citation_id}`}>Open citation</a>}</div></article>)}</div>:<p className="text-sm text-muted-foreground">No evidence relationships have been published yet.</p>}</CardContent></Card><Card><CardHeader><h2 className="font-semibold">Live timeline</h2></CardHeader><CardContent><ol className="max-h-[32rem] space-y-3 overflow-auto" aria-label="Investigation event timeline">{view.timeline.map(item=><li className="grid grid-cols-[auto_1fr] gap-3" key={item.event_id}><div className="mt-1 flex h-7 w-7 items-center justify-center rounded-full border"><GitBranch className="h-3.5 w-3.5"/></div><div><p className="text-sm font-medium">#{item.sequence_number} {item.title}</p><p className="text-xs text-muted-foreground">{item.event_type} · {new Date(item.occurred_at).toLocaleString()}</p>{item.detail&&<p className="mt-1 text-sm">{item.detail}</p>}</div></li>)}{!view.timeline.length&&<li className="text-sm text-muted-foreground">No durable events recorded yet.</li>}</ol></CardContent></Card></div>
          {(view.status==="FAILED"||view.status==="CANCELLED")&&<Card><CardContent className="flex items-start gap-3 py-4">{view.status==="FAILED"?<XCircle className="h-5 w-5 text-red-600"/>:<Square className="h-5 w-5 text-muted-foreground"/>}<div><p className="font-medium">Investigation {view.status.toLowerCase()}</p><p className="text-sm text-muted-foreground">{view.cancel_reason||"The authoritative investigation is terminal. Reconcile to verify the final journal state."}</p></div></CardContent></Card>}
        </>}
      </div>
    </div>
  </div>;
}
