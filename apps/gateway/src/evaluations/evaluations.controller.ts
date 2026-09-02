import { Body,Controller,Get,Headers,Param,Post,Query } from "@nestjs/common";
import { EvaluationsService } from "./evaluations.service";
@Controller("evaluations")
export class EvaluationsController {constructor(private readonly service:EvaluationsService){}
 @Get("runs") runs(@Headers("x-tenant-id") tenant:string,@Headers("x-correlation-id") corr:string,@Query("dataset_id") dataset?:string){return this.service.runs(tenant,dataset,corr);}
 @Get("runs/:runId/cases") cases(@Headers("x-tenant-id") tenant:string,@Headers("x-correlation-id") corr:string,@Param("runId") runId:string){return this.service.cases(tenant,runId,corr);}
 @Get("compare") compare(@Headers("x-tenant-id") tenant:string,@Headers("x-correlation-id") corr:string,@Query("baseline_run_id") baseline:string,@Query("candidate_run_id") candidate:string){return this.service.compare(tenant,baseline,candidate,corr);}
 @Get("regression-gate") gate(@Headers("x-tenant-id") tenant:string,@Headers("x-correlation-id") corr:string,@Query("baseline_run_id") baseline:string,@Query("candidate_run_id") candidate:string){return this.service.gate(tenant,baseline,candidate,corr);}
 @Post("baselines/promote") promote(@Headers("x-tenant-id") tenant:string,@Headers("x-correlation-id") corr:string,@Body() body:unknown){return this.service.promote(tenant,body,corr);}
 @Post("overrides") override(@Headers("x-tenant-id") tenant:string,@Headers("x-correlation-id") corr:string,@Body() body:unknown){return this.service.override(tenant,body,corr);}
}
