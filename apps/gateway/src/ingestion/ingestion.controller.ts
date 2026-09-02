import { BadRequestException, Body, Controller, Get, Headers, HttpCode, Param, Post, UploadedFile, UseInterceptors } from "@nestjs/common";
import { FileInterceptor } from "@nestjs/platform-express";
import { diskStorage } from "multer";
import { randomUUID } from "node:crypto";
import { unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { IngestionService } from "./ingestion.service";
import type { Modality, CreateUploadHandoffRequest, CompleteUploadHandoffRequest } from "./ingestion.dto";

function required(value:string|undefined,name:string):string { if(!value?.trim()) throw new BadRequestException(`${name} header is required`); return value.trim(); }
function uploadLimit(envName:string,fallback:number){return FileInterceptor("file",{storage:diskStorage({destination:tmpdir(),filename:(_r,_f,cb)=>cb(null,`verideploy-${randomUUID()}.upload`)}),limits:{fileSize:Number(process.env[envName]??fallback),files:1}});}
const documentUpload=uploadLimit("MAX_DOCUMENT_UPLOAD_BYTES",26214400);
const imageUpload=uploadLimit("MAX_IMAGE_UPLOAD_BYTES",26214400);
const audioUpload=uploadLimit("MAX_AUDIO_UPLOAD_BYTES",104857600);
const videoUpload=uploadLimit("MAX_VIDEO_UPLOAD_BYTES",524288000);

@Controller("ingestion")
export class IngestionController {
  constructor(private svc:IngestionService){}

  private async receive(file:Express.Multer.File|undefined, modality:Modality, tenant:string|undefined,user:string|undefined,idempotency:string|undefined,correlation:string|undefined){
    if(!file) throw new BadRequestException("file is required");
    const tenantId=required(tenant,"x-tenant-id"), userId=required(user,"x-user-id"), key=required(idempotency,"idempotency-key");
    if(key.length<8) throw new BadRequestException("Idempotency-Key must contain at least 8 characters");
    try{return await this.svc.accept(file,modality,tenantId,userId,key,correlation??randomUUID());}
    finally{await unlink(file.path).catch(()=>undefined);}
  }

  @Post("documents") @HttpCode(202) @UseInterceptors(documentUpload)
  documents(@UploadedFile() f:Express.Multer.File,@Headers("x-tenant-id") t?:string,@Headers("x-user-id") u?:string,@Headers("idempotency-key") i?:string,@Headers("x-correlation-id") c?:string){return this.receive(f,"document",t,u,i,c);}
  @Post("images") @HttpCode(202) @UseInterceptors(imageUpload)
  images(@UploadedFile() f:Express.Multer.File,@Headers("x-tenant-id") t?:string,@Headers("x-user-id") u?:string,@Headers("idempotency-key") i?:string,@Headers("x-correlation-id") c?:string){return this.receive(f,"image",t,u,i,c);}
  @Post("audio") @HttpCode(202) @UseInterceptors(audioUpload)
  audio(@UploadedFile() f:Express.Multer.File,@Headers("x-tenant-id") t?:string,@Headers("x-user-id") u?:string,@Headers("idempotency-key") i?:string,@Headers("x-correlation-id") c?:string){return this.receive(f,"audio",t,u,i,c);}
  @Post("video") @HttpCode(202) @UseInterceptors(videoUpload)
  video(@UploadedFile() f:Express.Multer.File,@Headers("x-tenant-id") t?:string,@Headers("x-user-id") u?:string,@Headers("idempotency-key") i?:string,@Headers("x-correlation-id") c?:string){return this.receive(f,"video",t,u,i,c);}


  @Post("uploads/handoff") @HttpCode(201)
  handoff(@Body() body:CreateUploadHandoffRequest,@Headers("x-tenant-id") t?:string,@Headers("x-user-id") u?:string,@Headers("idempotency-key") i?:string,@Headers("x-correlation-id") c?:string){const tenant=required(t,"x-tenant-id"),user=required(u,"x-user-id"),key=required(i,"idempotency-key");if(!/^[a-fA-F0-9]{64}$/.test(body.sha256??"")||!Number.isInteger(body.size_bytes)||body.size_bytes<=0)throw new BadRequestException("valid sha256 and size_bytes are required");return this.svc.createHandoff(body,tenant,user,key,c??randomUUID());}
  @Post("uploads/:jobId/complete") @HttpCode(202)
  complete(@Param("jobId") jobId:string,@Body() body:CompleteUploadHandoffRequest,@Headers("x-tenant-id") t?:string,@Headers("x-user-id") u?:string,@Headers("idempotency-key") i?:string,@Headers("x-correlation-id") c?:string){return this.svc.completeHandoff(jobId,body,required(t,"x-tenant-id"),required(u,"x-user-id"),required(i,"idempotency-key"),c??randomUUID());}

  @Get("jobs/:id")
  async job(@Param("id") id:string,@Headers("x-tenant-id") t?:string,@Headers("x-correlation-id") c?:string){return this.svc.get(id,required(t,"x-tenant-id"),c??randomUUID());}
}
