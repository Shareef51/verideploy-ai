import { Controller,Get,Headers,HttpException,Param } from "@nestjs/common";
import { CitationsService } from "./citations.service";
function required(v:string|undefined,name:string){if(!v?.trim())throw new HttpException(`${name} is required`,400);return v.trim();}
@Controller("citations")
export class CitationsController{
  constructor(private readonly citations:CitationsService){}
  @Get(":citationId") async preview(@Param("citationId") citationId:string,@Headers("x-tenant-id") tenant?:string,@Headers("x-correlation-id") correlation?:string){
    const r=await this.citations.preview(required(tenant,"x-tenant-id"),correlation?.trim()||crypto.randomUUID(),required(citationId,"citationId"));
    if(r.statusCode>=400)throw new HttpException(r.body as Record<string, any>,r.statusCode);return r.body;
  }
}
