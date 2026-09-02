import { ConflictException, Injectable, NotFoundException } from "@nestjs/common";
import { createHash } from "node:crypto";
import type { CreatePostmortemRequest, ReviewPostmortemRequest } from "./postmortems.dto";
import { PostmortemKafkaPublisher } from "./postmortem.kafka";
import { PrivateAiClient } from "../boundary/private-ai.client";
function stableUuid(tenantId:string,key:string):string{const d=createHash("sha256").update(`${tenantId}:postmortem:${key}`).digest();const b=Buffer.from(d.subarray(0,16));b[6]=((b[6]??0)&0x0f)|0x50;b[8]=((b[8]??0)&0x3f)|0x80;const h=b.toString("hex");return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;}
@Injectable()
export class PostmortemsService{
  constructor(private readonly kafka:PostmortemKafkaPublisher,private readonly ai:PrivateAiClient){}
  async create(input:CreatePostmortemRequest,tenantId:string,userId:string,key:string,correlationId:string){const postmortemId=stableUuid(tenantId,key);await this.kafka.publish({postmortem_id:postmortemId,tenant_id:tenantId,investigation_id:input.investigation_id,requested_by:userId,correlation_id:correlationId,idempotency_key:key,title:input.title,reviewed_evidence:input.reviewed_evidence});return {postmortem_id:postmortemId,status:"QUEUED",authoritative:false,correlation_id:correlationId};}
  list(t:string,c:string){return this.ai.request("/internal/v1/postmortems",t,c);}
  async get(id:string,t:string,c:string){const r=await this.ai.request(`/internal/v1/postmortems/${encodeURIComponent(id)}`,t,c);if(r.statusCode===404)throw new NotFoundException("postmortem not found");return r;}
  async review(id:string,body:ReviewPostmortemRequest,t:string,u:string,c:string){const r=await this.ai.request(`/internal/v1/postmortems/${encodeURIComponent(id)}/review`,t,c,{method:"POST",body:{postmortem_id:id,tenant_id:t,reviewer_id:u,correlation_id:c,...body},retry:false});if(r.statusCode===404)throw new NotFoundException("postmortem not found");if(r.statusCode===409)throw new ConflictException(r.body);return r;}
  async export(id:string,format:string,t:string,c:string){const r=await this.ai.request(`/internal/v1/postmortems/${encodeURIComponent(id)}/export?format=${encodeURIComponent(format)}`,t,c);if(r.statusCode===404)throw new NotFoundException("postmortem not found");if(r.statusCode===409)throw new ConflictException(r.body);return r;}
}
