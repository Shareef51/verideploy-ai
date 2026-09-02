import { Controller,Get,Headers,Query,ForbiddenException } from "@nestjs/common";
import { AuditService } from "./audit.service";
@Controller("audit") export class AuditController{constructor(private readonly service:AuditService){}
 @Get("events") events(@Headers("x-tenant-id") t:string,@Headers("x-user-id") u:string,@Headers("x-auth-roles") r:string,@Headers("x-correlation-id") c:string,@Query() q:Record<string,string|undefined>){return this.service.search(t,u,r,q,c);}
 @Get("export") exportAudit(@Headers("x-tenant-id") t:string,@Headers("x-user-id") u:string,@Headers("x-auth-roles") r:string,@Headers("x-correlation-id") c:string,@Query("format") f="jsonl"){if(!r.split(",").some(x=>["security_admin","auditor"].includes(x)))throw new ForbiddenException("audit export requires security_admin or auditor");return this.service.export(t,u,r,f,c);}
}
