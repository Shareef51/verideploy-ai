import { Injectable } from "@nestjs/common";
import { PrivateAiClient } from "../boundary/private-ai.client";
@Injectable() export class AuditService{
 constructor(private readonly ai:PrivateAiClient){}
 search(tenant:string,user:string,roles:string,query:Record<string,string|undefined>,corr:string){const p=new URLSearchParams();for(const [k,v] of Object.entries(query))if(v)p.set(k,v);return this.ai.request(`/internal/v1/audit/events?${p.toString()}`,tenant,corr,{method:"GET",headers:{"x-user-id":user,"x-auth-roles":roles}});}
 export(tenant:string,user:string,roles:string,format:string,corr:string){return this.ai.request(`/internal/v1/audit/export?format=${encodeURIComponent(format)}`,tenant,corr,{method:"GET",headers:{"x-user-id":user,"x-auth-roles":roles}});}
}
