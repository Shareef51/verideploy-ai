import { Controller,Get,Headers,HttpException,Query } from "@nestjs/common";
import { EvidenceGraphService } from "./evidence-graph.service";
function required(value:string|undefined,name:string){if(!value?.trim())throw new HttpException(`${name} is required`,400);return value.trim();}
@Controller("evidence-graph")
export class EvidenceGraphController{
  constructor(private readonly graph:EvidenceGraphService){}
  @Get("snapshot") async snapshot(@Headers("x-tenant-id") tenant?:string,@Headers("x-correlation-id") correlation?:string){const r=await this.graph.snapshot(required(tenant,"x-tenant-id"),correlation?.trim()||crypto.randomUUID());if(r.statusCode>=400)throw new HttpException(r.body as Record<string, any>,r.statusCode);return r.body;}
  @Get("path") async path(@Query("source_entity_id") source?:string,@Query("target_entity_id") target?:string,@Query("max_depth") maxDepth="6",@Headers("x-tenant-id") tenant?:string,@Headers("x-correlation-id") correlation?:string){const r=await this.graph.path(required(tenant,"x-tenant-id"),correlation?.trim()||crypto.randomUUID(),required(source,"source_entity_id"),required(target,"target_entity_id"),Math.min(12,Math.max(1,Number(maxDepth)||6)));if(r.statusCode>=400)throw new HttpException(r.body as Record<string, any>,r.statusCode);return r.body;}
}
