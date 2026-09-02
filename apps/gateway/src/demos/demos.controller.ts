import { Controller, Get, Headers, Param, Post, BadRequestException } from "@nestjs/common";
import { randomUUID } from "node:crypto";
import { DemosService } from "./demos.service";
function req(v:string|undefined,n:string){if(!v?.trim())throw new BadRequestException(`${n} header is required`);return v.trim();}
@Controller("demos")
export class DemosController{
 constructor(private svc:DemosService){}
 @Get() list(){return {synthetic:true,demos:this.svc.list()};}
 @Post(":id/run") run(@Param("id") id:string,@Headers("x-tenant-id") tenant?:string,@Headers("x-user-id") user?:string,@Headers("x-correlation-id") corr?:string){return this.svc.run(id,req(tenant,"x-tenant-id"),req(user,"x-user-id"),corr??randomUUID());}
}
