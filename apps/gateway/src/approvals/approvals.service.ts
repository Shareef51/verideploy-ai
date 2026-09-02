import { Injectable } from "@nestjs/common";
import { PrivateAiClient } from "../boundary/private-ai.client";
@Injectable()
export class ApprovalsService {
  constructor(private readonly ai:PrivateAiClient){}
  create(tenantId:string,correlationId:string,body:Record<string,unknown>){return this.ai.request(`/internal/v1/approvals`,tenantId,correlationId,{method:"POST",body,retry:false});}
  queue(tenantId:string,correlationId:string,reviewerId:string,roles:string[]){const params=new URLSearchParams({reviewer_id:reviewerId,reviewer_roles:roles.join(",")});return this.ai.request(`/internal/v1/approvals/queue?${params.toString()}`,tenantId,correlationId,{headers:{"x-user-id":reviewerId,"x-auth-roles":roles.join(",")}});}
  get(tenantId:string,correlationId:string,approvalId:string){return this.ai.request(`/internal/v1/approvals/${encodeURIComponent(approvalId)}`,tenantId,correlationId);}
  decide(tenantId:string,correlationId:string,approvalId:string,reviewerId:string,roles:string[],decision:string,comment:string|undefined,expectedVersion:number){const body={tenant_id:tenantId,approval_id:approvalId,reviewer:{reviewer_id:reviewerId,roles},decision,comment:comment??null,expected_version:expectedVersion};return this.ai.request(`/internal/v1/approvals/${encodeURIComponent(approvalId)}/decision`,tenantId,correlationId,{method:"POST",body,retry:false,headers:{"x-user-id":reviewerId,"x-auth-roles":roles.join(",")}});}
}
