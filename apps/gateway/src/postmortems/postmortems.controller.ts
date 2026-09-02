import { BadRequestException, Body, Controller, Get, Headers, Param, Post, Query, Res } from "@nestjs/common";
import { Response } from "express";
import type { CreatePostmortemRequest, ReviewPostmortemRequest } from "./postmortems.dto";
import { PostmortemsService } from "./postmortems.service";
function req(v:string|undefined,n:string){if(!v)throw new BadRequestException(`${n} header is required`);return v;}
@Controller("postmortems") export class PostmortemsController{
 constructor(private readonly service:PostmortemsService){}
 @Post() create(@Body() body:CreatePostmortemRequest,@Headers("x-tenant-id")t?:string,@Headers("x-user-id")u?:string,@Headers("idempotency-key")k?:string,@Headers("x-correlation-id")c?:string){return this.service.create(body,req(t,"x-tenant-id"),req(u,"x-user-id"),req(k,"idempotency-key"),req(c,"x-correlation-id"));}
 @Get() async list(@Headers("x-tenant-id")t?:string,@Headers("x-correlation-id")c?:string,@Res()res?:Response){const r=await this.service.list(req(t,"x-tenant-id"),req(c,"x-correlation-id"));return res!.status(r.statusCode).json(r.body);}
 @Get(":id") async get(@Param("id")id:string,@Headers("x-tenant-id")t?:string,@Headers("x-correlation-id")c?:string,@Res()res?:Response){const r=await this.service.get(id,req(t,"x-tenant-id"),req(c,"x-correlation-id"));return res!.status(r.statusCode).json(r.body);}
 @Post(":id/review") async review(@Param("id")id:string,@Body()body:ReviewPostmortemRequest,@Headers("x-tenant-id")t?:string,@Headers("x-user-id")u?:string,@Headers("x-correlation-id")c?:string,@Res()res?:Response){const r=await this.service.review(id,body,req(t,"x-tenant-id"),req(u,"x-user-id"),req(c,"x-correlation-id"));return res!.status(r.statusCode).json(r.body);}
 @Get(":id/export") async export(@Param("id")id:string,@Query("format")format="markdown",@Headers("x-tenant-id")t?:string,@Headers("x-correlation-id")c?:string,@Res()res?:Response){const r=await this.service.export(id,format,req(t,"x-tenant-id"),req(c,"x-correlation-id"));return res!.status(r.statusCode).json(r.body);}
}
