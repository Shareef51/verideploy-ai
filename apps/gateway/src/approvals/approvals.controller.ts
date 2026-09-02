import { Body,Controller,Get,Headers,HttpException,Param,Post } from "@nestjs/common";
import { ApprovalsService } from "./approvals.service";
function required(v:string|undefined,name:string){if(!v?.trim())throw new HttpException(`${name} is required`,400);return v.trim();}
function roles(v:string|undefined){const result=required(v,"x-auth-roles").split(",").map(x=>x.trim()).filter(Boolean);if(!result.length)throw new HttpException("x-auth-roles is required",400);return result;}
@Controller("approvals")
export class ApprovalsController{
  constructor(private readonly approvals:ApprovalsService){}
  private corr(c?:string){return c?.trim()||crypto.randomUUID();}
  @Get() async queue(@Headers("x-tenant-id") tenant?:string,@Headers("x-user-id") user?:string,@Headers("x-auth-roles") authRoles?:string,@Headers("x-correlation-id") correlation?:string){const r=await this.approvals.queue(required(tenant,"x-tenant-id"),this.corr(correlation),required(user,"x-user-id"),roles(authRoles));if(r.statusCode>=400)throw new HttpException(r.body as Record<string, any>,r.statusCode);return r.body;}
  @Get(":approvalId") async get(@Param("approvalId") id:string,@Headers("x-tenant-id") tenant?:string,@Headers("x-correlation-id") correlation?:string){const r=await this.approvals.get(required(tenant,"x-tenant-id"),this.corr(correlation),required(id,"approvalId"));if(r.statusCode>=400)throw new HttpException(r.body as Record<string, any>,r.statusCode);return r.body;}
  @Post(":approvalId/decision") async decide(@Param("approvalId") id:string,@Body() body:{decision:string;comment?:string;expected_version:number},@Headers("x-tenant-id") tenant?:string,@Headers("x-user-id") user?:string,@Headers("x-auth-roles") authRoles?:string,@Headers("x-correlation-id") correlation?:string){const t=required(tenant,"x-tenant-id");if(!["approve","reject","request_changes"].includes(body.decision))throw new HttpException("invalid decision",422);if(!Number.isInteger(body.expected_version)||body.expected_version<1)throw new HttpException("expected_version must be positive",422);const r=await this.approvals.decide(t,this.corr(correlation),required(id,"approvalId"),required(user,"x-user-id"),roles(authRoles),body.decision,body.comment,body.expected_version);if(r.statusCode>=400)throw new HttpException(r.body as Record<string, any>,r.statusCode);return r.body;}
}
