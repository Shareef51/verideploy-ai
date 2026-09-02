import { Injectable, NotFoundException, ServiceUnavailableException } from "@nestjs/common";
import { randomUUID } from "node:crypto";
import { stat } from "node:fs/promises";
import { resolve, basename } from "node:path";
import { ReleasesService } from "../releases/releases.service";
import { InvestigationsService } from "../investigations/investigations.service";
import { IngestionService } from "../ingestion/ingestion.service";
import { ApprovalsService } from "../approvals/approvals.service";
import type { Modality } from "../ingestion/ingestion.dto";

type DemoKind="release-risk"|"incident-rca"|"screenshot"|"architecture"|"recording";
type DemoDefinition={id:string;title:string;kind:DemoKind;description:string;workspace_href:string;asset?:string;modality?:Modality};
type KillerEvidence={evidence_id:string;citation_id:string;label:string;asset:string;modality:Modality};
const DEMOS:ReadonlyArray<DemoDefinition>=[
 {id:"release-risk",title:"Release Risk — Checkout API v2.19.0",kind:"release-risk",description:"High-confidence release assurance run with migration and rollback evidence.",workspace_href:"/release-risk"},
 {id:"incident-rca",title:"Incident RCA — Checkout latency regression",kind:"incident-rca",description:"Durable RCA investigation with evidence, citations, critic, audit and live reconciliation.",workspace_href:"/incidents"},
 {id:"screenshot",title:"Screenshot — Grafana latency anomaly",kind:"screenshot",description:"Synthetic Grafana screenshot enters the real image-ingestion path before investigation.",workspace_href:"/evidence",asset:"data/demos/checkout-grafana-synthetic.png",modality:"image"},
 {id:"architecture",title:"Architecture — Checkout dependency change",kind:"architecture",description:"Synthetic architecture PDF enters document ingestion and launches topology-aware investigation.",workspace_href:"/topology",asset:"data/demos/checkout-architecture-synthetic.pdf",modality:"document"},
 {id:"recording",title:"Recording — Incident screen recording",kind:"recording",description:"Synthetic MP4 recording enters video ingestion and launches incident investigation.",workspace_href:"/incidents",asset:"data/demos/checkout-incident-recording-synthetic.mp4",modality:"video"},
] as const;
const KILLER_EVIDENCE:ReadonlyArray<KillerEvidence>=[
 {evidence_id:"ev-pr",citation_id:"cit-pr",label:"Synthetic pull request",asset:"data/demos/multimodal-killer-demo/checkout-pr-synthetic.txt",modality:"document"},
 {evidence_id:"ev-architecture",citation_id:"cit-architecture",label:"Synthetic architecture PDF",asset:"data/demos/checkout-architecture-synthetic.pdf",modality:"document"},
 {evidence_id:"ev-grafana",citation_id:"cit-grafana",label:"Synthetic Grafana screenshot",asset:"data/demos/checkout-grafana-synthetic.png",modality:"image"},
 {evidence_id:"ev-video",citation_id:"cit-video",label:"Synthetic incident recording",asset:"data/demos/checkout-incident-recording-synthetic.mp4",modality:"video"},
 {evidence_id:"ev-runbook",citation_id:"cit-runbook",label:"Synthetic incident runbook",asset:"data/demos/multimodal-killer-demo/checkout-runbook-synthetic.txt",modality:"document"},
 {evidence_id:"ev-runtime",citation_id:"cit-runtime",label:"Synthetic runtime signals",asset:"data/demos/multimodal-killer-demo/checkout-runtime-signals-synthetic.txt",modality:"document"},
 {evidence_id:"ev-history",citation_id:"cit-history",label:"Synthetic historical RCA",asset:"data/demos/multimodal-killer-demo/checkout-historical-rca-synthetic.txt",modality:"document"},
] as const;

@Injectable()
export class DemosService{
 constructor(private releases:ReleasesService,private investigations:InvestigationsService,private ingestion:IngestionService,private approvals:ApprovalsService){}
 list(){return DEMOS.map(d=>({...d,synthetic:true,one_click:true,asset:d.asset?basename(d.asset):null}));}
 private get(id:string){const demo=DEMOS.find(x=>x.id===id);if(!demo)throw new NotFoundException("demo not found");return demo;}
 private async ingestAsset(asset:string,modality:Modality,tenantId:string,userId:string,idempotencyKey:string,correlationId:string){const path=resolve(process.cwd(),asset);const info=await stat(path);const file={fieldname:"file",originalname:basename(path),encoding:"7bit",mimetype:"application/octet-stream",size:info.size,destination:"",filename:basename(path),path,buffer:Buffer.alloc(0),stream:undefined} as unknown as Express.Multer.File;return this.ingestion.accept(file,modality,tenantId,userId,idempotencyKey,correlationId);}
 async run(id:string,tenantId:string,userId:string,correlationId:string){
   if(id==="multimodal-killer") return this.runMultimodalKiller(tenantId,userId,correlationId);
   const demo=this.get(id); const runId=randomUUID(); const prefix=`synthetic-demo:${demo.id}:${runId}`;
   if(demo.kind==="release-risk"){
     const accepted=await this.releases.createRiskAssessment({repository:"verideploy/nexuspay-checkout",release_id:"checkout-v2.19.0",commit_sha:"9f71a83d1c2b4e5f6a7b8c9d0e1f2a3b4c5d6e7f",target_environment:"production",changed_file_details:[{path:"services/checkout/db/pool.ts",additions:31,deletions:7,language:"TypeScript",change_type:"modified"},{path:"migrations/219_add_checkout_idx.sql",additions:18,deletions:0,language:"SQL",change_type:"added"}],policy:{changed_files:2,changed_services:1,failed_workflows:0,database_migration_changed:true,rollback_plan_verified:true,production_incidents_last_30d:2,high_severity_incidents_last_30d:1,test_coverage_delta_percent:-1.4,security_scan_critical_findings:0,deployment_window_risk:4}},tenantId,userId,prefix,correlationId);
     return {run_id:runId,demo_id:id,synthetic:true,kind:demo.kind,status:"QUEUED",workspace_href:demo.workspace_href,accepted};
   }
   let ingestionJob:unknown=null;
   if(demo.asset&&demo.modality) ingestionJob=await this.ingestAsset(demo.asset,demo.modality,tenantId,userId,`${prefix}:ingest`,correlationId);
   const query=demo.kind==="incident-rca"?"Investigate the synthetic checkout latency regression after release checkout-v2.19.0 and determine the most likely root cause with citations.":`Analyze the synthetic ${demo.kind} evidence${(ingestionJob as any)?.job_id?` from ingestion job ${(ingestionJob as any).job_id}`:""}; correlate it with checkout-v2.19.0, produce evidence-backed RCA, citations, critic result, audit trail, and final status.`;
   const investigation=await this.investigations.create({query,incident_id:"INC-SYNTHETIC-CHECKOUT-73"},tenantId,userId,`${prefix}:investigation`,correlationId);
   return {run_id:runId,demo_id:id,synthetic:true,kind:demo.kind,status:"QUEUED",workspace_href:demo.workspace_href,ingestion_job:ingestionJob,investigation};
 }
 async runMultimodalKiller(tenantId:string,userId:string,correlationId:string){
   const runId=randomUUID(); const prefix=`synthetic-demo:multimodal-killer:${runId}`; const ingestions=[] as Array<Record<string,unknown>>;
   for(const evidence of KILLER_EVIDENCE){
     const accepted=await this.ingestAsset(evidence.asset,evidence.modality,tenantId,userId,`${prefix}:ingest:${evidence.evidence_id}`,correlationId);
     ingestions.push({...evidence,job_id:(accepted as any).job_id,sha256:(accepted as any).sha256,status:(accepted as any).status});
   }
   const evidenceLines=ingestions.map(x=>`${x.evidence_id}:${x.job_id}:${x.citation_id}`).join(", ");
   const investigation=await this.investigations.create({query:`MULTIMODAL SYNTHETIC DEMO. Correlate PR, architecture PDF, Grafana screenshot, incident video, runbook, runtime signals and historical RCA. Evidence jobs: ${evidenceLines}. Determine whether checkout-v2.19.0 caused DB pool contention; run the RCA critic, preserve every citation, estimate latency/cost, and require human review before any rollback action.`,incident_id:"INC-SYNTHETIC-CHECKOUT-74"},tenantId,userId,`${prefix}:investigation`,correlationId);
   const approvalBody={tenant_id:tenantId,run_id:runId,investigation_id:(investigation as any).investigation_id,action_type:"release.rollback",action_payload:{release_id:"checkout-v2.19.0",dry_run:true,execution_disabled:true},risk:"high",risk_score:93,requested_by:userId,evidence_summary:{title:"Synthetic checkout rollback review",summary:"Multimodal evidence points to release-related checkout DB pool contention. Rollback remains blocked until a human release reviewer approves.",evidence_ids:KILLER_EVIDENCE.map(x=>x.evidence_id),citation_ids:KILLER_EVIDENCE.map(x=>x.citation_id),risk_factors:["database concurrency change","latency regression","production rollback"]},policy:{policy_id:"multimodal-killer-recruiter-demo",min_risk_score:80,required_roles:["release_reviewer"],expiry_seconds:3600,allow_delegation:true,require_comment_on_reject:true},idempotency_key:`${prefix}:approval`};
   const approval=await this.approvals.create(tenantId,correlationId,approvalBody);
   if(approval.statusCode>=400) throw new ServiceUnavailableException({code:"APPROVAL_GATE_UNAVAILABLE",message:"Multimodal demo investigation queued but review gate could not be created"});
   return {run_id:runId,demo_id:"multimodal-killer",synthetic:true,status:"QUEUED",workspace_href:"/demos/multimodal-killer",investigation,evidence:ingestions,approval:approval.body,explainability:{root_cause:"Checkout database pool contention introduced by release checkout-v2.19.0",confidence:0.93,critic_status:"SUPPORTED_WITH_ALTERNATIVE_CHECK",decision:"ROLLBACK_REQUIRES_HUMAN_APPROVAL",latency_budget_ms:2500,estimated_cost_usd:0.084,citations:KILLER_EVIDENCE.map(x=>x.citation_id),graph_nodes:["evidence_ingestion","multimodal_extraction","retrieval_and_correlation","incident_rca","rca_critic","decision_policy","human_review_gate"]}};
 }
}
