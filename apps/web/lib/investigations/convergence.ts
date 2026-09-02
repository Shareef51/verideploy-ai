import { z } from "zod";

const TimelineItemSchema=z.object({event_id:z.string(),sequence_number:z.number().int().nonnegative(),event_type:z.string(),occurred_at:z.string(),title:z.string(),detail:z.string().nullable().optional(),node:z.string().nullable().optional(),status:z.string().nullable().optional()});
const HypothesisSchema=z.object({hypothesis_id:z.string(),title:z.string(),status:z.string(),confidence:z.number().min(0).max(1),supporting_evidence_ids:z.array(z.string()),disconfirming_evidence_ids:z.array(z.string()),updated_sequence:z.number().int().nonnegative()});
const RootCauseSchema=z.object({hypothesis_id:z.string().nullable().optional(),summary:z.string(),confidence:z.number().min(0).max(1),determined:z.boolean(),evidence_ids:z.array(z.string()),updated_sequence:z.number().int().nonnegative()});
const EvidenceSchema=z.object({evidence_id:z.string(),label:z.string(),evidence_type:z.string(),relation:z.string(),hypothesis_id:z.string().nullable().optional(),citation_id:z.string().nullable().optional(),updated_sequence:z.number().int().nonnegative()});
export const InvestigationProjectionSchema=z.object({investigation_id:z.string(),correlation_id:z.string(),incident_id:z.string().nullable().optional(),query:z.string(),status:z.string(),cancel_requested:z.boolean(),cancel_reason:z.string().nullable().optional(),last_sequence_number:z.number().int().nonnegative(),updated_at:z.string(),timeline:z.array(TimelineItemSchema),hypotheses:z.array(HypothesisSchema),root_cause:RootCauseSchema.nullable(),alternatives:z.array(RootCauseSchema),evidence_map:z.array(EvidenceSchema),convergence_sha256:z.string().length(64)});
export type InvestigationProjection=z.infer<typeof InvestigationProjectionSchema>;
export const InvestigationEventSchema=z.object({event_id:z.string(),event_type:z.string(),investigation_id:z.string(),sequence_number:z.number().int().positive(),occurred_at:z.string(),payload:z.record(z.string(),z.unknown())});
export type InvestigationEvent=z.infer<typeof InvestigationEventSchema>;

function strings(value:unknown):string[]{return Array.isArray(value)?[...new Set(value.map(String))].sort():[]}
function confidence(value:unknown):number{const n=Number(value);return Number.isFinite(n)?Math.max(0,Math.min(1,n)):0}
function text(value:unknown):string{return typeof value==="string"?value:""}

export function isContiguous(view:InvestigationProjection,event:InvestigationEvent):boolean{return event.sequence_number===view.last_sequence_number+1}

export function reduceInvestigationEvent(view:InvestigationProjection,event:InvestigationEvent):InvestigationProjection{
  if(event.sequence_number<=view.last_sequence_number)return view;
  if(!isContiguous(view,event))throw new Error(`investigation event sequence gap: expected ${view.last_sequence_number+1}, got ${event.sequence_number}`);
  const payload=event.payload;
  const timeline=[...view.timeline,{event_id:event.event_id,sequence_number:event.sequence_number,event_type:event.event_type,occurred_at:event.occurred_at,title:text(payload.message)||text(payload.title)||event.event_type.replaceAll("."," "),detail:text(payload.detail)||text(payload.reason)||null,node:text(payload.node)||null,status:text(payload.status)||null}];
  let hypotheses=view.hypotheses;
  let rootCause=view.root_cause;
  let alternatives=view.alternatives;
  let evidenceMap=view.evidence_map;
  let status=view.status;
  let cancelRequested=view.cancel_requested;
  let cancelReason=view.cancel_reason;
  if(event.event_type==="investigation.status.changed"&&text(payload.status)){status=text(payload.status);if(status==="CANCELLING")cancelRequested=true;}
  if(event.event_type==="investigation.cancelled"){status="CANCELLED";cancelRequested=true;cancelReason=text(payload.reason)||cancelReason;}
  if(event.event_type==="investigation.hypothesis.updated"){
    const id=text(payload.hypothesis_id),title=text(payload.title)||text(payload.summary);
    if(id&&title){const next={hypothesis_id:id,title,status:text(payload.status)||"candidate",confidence:confidence(payload.confidence),supporting_evidence_ids:strings(payload.supporting_evidence_ids),disconfirming_evidence_ids:strings(payload.disconfirming_evidence_ids),updated_sequence:event.sequence_number};hypotheses=[...hypotheses.filter(item=>item.hypothesis_id!==id),next].sort((a,b)=>b.confidence-a.confidence||a.hypothesis_id.localeCompare(b.hypothesis_id));}
  }
  if(event.event_type==="investigation.rca.updated"){
    const summary=text(payload.summary)||text(payload.root_cause);
    if(summary)rootCause={hypothesis_id:text(payload.hypothesis_id)||null,summary,confidence:confidence(payload.confidence),determined:Boolean(payload.determined),evidence_ids:strings(payload.evidence_ids),updated_sequence:event.sequence_number};
    if(Array.isArray(payload.alternatives)){alternatives=payload.alternatives.flatMap((raw,index)=>{if(!raw||typeof raw!=="object")return[];const item=raw as Record<string,unknown>,summary=text(item.summary)||text(item.title);if(!summary)return[];return[{hypothesis_id:text(item.hypothesis_id)||`alternative-${index}`,summary,confidence:confidence(item.confidence),determined:false,evidence_ids:strings(item.evidence_ids),updated_sequence:event.sequence_number}]});}
  }
  if(event.event_type==="investigation.evidence.linked"){
    const id=text(payload.evidence_id);if(id){const next={evidence_id:id,label:text(payload.label)||id,evidence_type:text(payload.evidence_type)||"evidence",relation:text(payload.relation)||"supports",hypothesis_id:text(payload.hypothesis_id)||null,citation_id:text(payload.citation_id)||null,updated_sequence:event.sequence_number};evidenceMap=[...evidenceMap.filter(item=>item.evidence_id!==id),next].sort((a,b)=>a.evidence_id.localeCompare(b.evidence_id));}
  }
  return {...view,status,cancel_requested:cancelRequested,cancel_reason:cancelReason,last_sequence_number:event.sequence_number,updated_at:event.occurred_at,timeline,hypotheses,root_cause:rootCause,alternatives,evidence_map:evidenceMap};
}

export function reduceInvestigationEvents(view:InvestigationProjection,events:InvestigationEvent[]):InvestigationProjection{return [...events].sort((a,b)=>a.sequence_number-b.sequence_number).reduce(reduceInvestigationEvent,view)}
