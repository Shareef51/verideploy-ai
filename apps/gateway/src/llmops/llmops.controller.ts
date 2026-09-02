import { Controller,Get,Headers,Param } from "@nestjs/common";
import { LLMOpsService } from "./llmops.service";
@Controller("llmops")
export class LLMOpsController { constructor(private readonly service:LLMOpsService){}
 @Get("correlations/:correlationId") trace(@Param("correlationId") id:string,@Headers("x-tenant-id") tenant:string,@Headers("x-correlation-id") corr?:string){ return this.service.trace(tenant,id,corr||id); }
}
