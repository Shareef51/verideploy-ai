import { Injectable, NotFoundException, ServiceUnavailableException } from "@nestjs/common";
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { basename } from "node:path";
import { PrivateAiClient } from "../boundary/private-ai.client";
import { detectMime, assertModality } from "./file-signature";
import { IngestionKafkaBridge } from "./ingestion.kafka";
import { ObjectStorage } from "./object-storage";
import type { Modality, CreateUploadHandoffRequest, CompleteUploadHandoffRequest } from "./ingestion.dto";

function stableUuid(tenantId:string,key:string){const d=createHash("sha256").update(`${tenantId}:ingestion:${key}`).digest();const b=Buffer.from(d.subarray(0,16));b[6]=((b[6]??0)&15)|80;b[8]=((b[8]??0)&63)|128;const h=b.toString("hex");return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;}
async function sha256(path:string){const h=createHash("sha256");for await(const c of createReadStream(path))h.update(c);return h.digest("hex");}

@Injectable()
export class IngestionService {
  constructor(private kafka:IngestionKafkaBridge,private storage:ObjectStorage,private ai:PrivateAiClient){}

  async accept(file:Express.Multer.File, modality:Modality, tenantId:string,userId:string,idempotencyKey:string,correlationId:string){
    const mime=await detectMime(file.path); assertModality(modality,mime); const digest=await sha256(file.path); const jobId=stableUuid(tenantId,idempotencyKey);
    const safe=basename(file.originalname).replace(/[^A-Za-z0-9._-]/g,"_").slice(0,180) || "evidence.bin";
    const key=`tenants/${tenantId}/ingestion/${jobId}/${digest.slice(0,16)}-${safe}`;
    const version=await this.storage.put(file.path,key,mime,digest);
    const command={job_id:jobId,tenant_id:tenantId,requested_by:userId,correlation_id:correlationId,idempotency_key:idempotencyKey,modality,original_filename:safe,detected_mime_type:mime,size_bytes:file.size,sha256:digest,bucket:this.storage.bucket,object_key:key,object_version:version};
    try{await this.kafka.publish(command);}catch(error){await this.storage.remove(key);throw new ServiceUnavailableException({code:"KAFKA_UNAVAILABLE",message:"Stored upload could not be queued for processing"},{cause:error});}
    return {job_id:jobId,correlation_id:correlationId,status:"QUEUED",detected_mime_type:mime,sha256:digest,size_bytes:file.size,authoritative:false};
  }

  async createHandoff(input:CreateUploadHandoffRequest,tenantId:string,userId:string,idempotencyKey:string,correlationId:string){const jobId=stableUuid(tenantId,idempotencyKey);const safe=basename(input.filename).replace(/[^A-Za-z0-9._-]/g,"_").slice(0,180)||"evidence.bin";const key=`tenants/${tenantId}/ingestion/${jobId}/${input.sha256.slice(0,16)}-${safe}`;const uploadUrl=await this.storage.createUploadHandoff(key,input.content_type,input.sha256,600);return {job_id:jobId,correlation_id:correlationId,upload_url:uploadUrl,method:"PUT",expires_in_seconds:600,required_headers:{"content-type":input.content_type,"x-amz-meta-sha256":input.sha256},object_ref:{bucket:this.storage.bucket,key},requested_by:userId};}
  async completeHandoff(jobId:string,input:CompleteUploadHandoffRequest,tenantId:string,userId:string,idempotencyKey:string,correlationId:string){if(stableUuid(tenantId,idempotencyKey)!==jobId)throw new Error("job id does not match idempotency key");const safe=basename(input.filename).replace(/[^A-Za-z0-9._-]/g,"_").slice(0,180)||"evidence.bin";const key=`tenants/${tenantId}/ingestion/${jobId}/${input.sha256.slice(0,16)}-${safe}`;const version=await this.storage.verify(key,{mime:input.content_type,sha256:input.sha256,sizeBytes:input.size_bytes});await this.kafka.publish({job_id:jobId,tenant_id:tenantId,requested_by:userId,correlation_id:correlationId,idempotency_key:idempotencyKey,modality:input.modality,original_filename:safe,detected_mime_type:input.content_type,size_bytes:input.size_bytes,sha256:input.sha256,bucket:this.storage.bucket,object_key:key,object_version:version});return {job_id:jobId,status:"QUEUED",correlation_id:correlationId,authoritative:false};}
  async get(jobId:string,tenantId:string,correlationId:string){const response=await this.ai.request(`/internal/v1/ingestion/jobs/${encodeURIComponent(jobId)}`,tenantId,correlationId);if(response.statusCode===404)throw new NotFoundException("ingestion job not found");if(response.statusCode>=400)throw new ServiceUnavailableException("ingestion state unavailable");return response.body;}
}
