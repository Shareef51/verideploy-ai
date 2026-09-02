import { Injectable } from "@nestjs/common";
import { PrivateAiClient } from "../boundary/private-ai.client";
@Injectable()
export class EvaluationsService {
 constructor(private readonly ai:PrivateAiClient){}
 runs(tenantId:string,datasetId:string|undefined,correlationId:string){const q=datasetId?`?dataset_id=${encodeURIComponent(datasetId)}`:"";return this.ai.get(`/internal/v1/evaluations/runs${q}`,{tenantId,correlationId});}
 cases(tenantId:string,runId:string,correlationId:string){return this.ai.get(`/internal/v1/evaluations/runs/${encodeURIComponent(runId)}/cases`,{tenantId,correlationId});}
 compare(tenantId:string,baseline:string,candidate:string,correlationId:string){return this.ai.get(`/internal/v1/evaluations/compare?baseline_run_id=${encodeURIComponent(baseline)}&candidate_run_id=${encodeURIComponent(candidate)}`,{tenantId,correlationId});}
 gate(tenantId:string,baseline:string,candidate:string,correlationId:string){return this.ai.get(`/internal/v1/evaluations/regression-gate?baseline_run_id=${encodeURIComponent(baseline)}&candidate_run_id=${encodeURIComponent(candidate)}`,{tenantId,correlationId});}
 promote(tenantId:string,body:unknown,correlationId:string){return this.ai.request(`/internal/v1/evaluations/baselines/promote`,tenantId,correlationId,{method:"POST",body});}
 override(tenantId:string,body:unknown,correlationId:string){return this.ai.request(`/internal/v1/evaluations/overrides`,tenantId,correlationId,{method:"POST",body});}
}
