import { Injectable, ServiceUnavailableException } from "@nestjs/common";
import { DeleteObjectCommand, HeadObjectCommand, PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import { createReadStream } from "node:fs";
@Injectable()
export class ObjectStorage {
  private client=new S3Client({region:process.env.S3_REGION??"us-east-1",endpoint:process.env.S3_ENDPOINT??"http://minio:9000",forcePathStyle:true,credentials:{accessKeyId:process.env.S3_ACCESS_KEY??"verideploy-local",secretAccessKey:process.env.S3_SECRET_KEY??"replace-in-local-env"}});
  readonly bucket=process.env.S3_BUCKET??"verideploy-evidence";
  async put(path:string,key:string,mime:string,sha256:string){try{const out=await this.client.send(new PutObjectCommand({Bucket:this.bucket,Key:key,Body:createReadStream(path),ContentType:mime,Metadata:{sha256}}));return out.VersionId??null;}catch(error){throw new ServiceUnavailableException({code:"OBJECT_STORE_UNAVAILABLE",message:"Evidence object could not be stored"},{cause:error});}}
  async createUploadHandoff(key:string,mime:string,sha256:string,expiresSeconds=600){try{return await getSignedUrl(this.client,new PutObjectCommand({Bucket:this.bucket,Key:key,ContentType:mime,Metadata:{sha256}}),{expiresIn:Math.min(900,Math.max(60,expiresSeconds))});}catch(error){throw new ServiceUnavailableException({code:"OBJECT_STORE_UNAVAILABLE",message:"Upload handoff could not be created"},{cause:error});}}
  async verify(key:string,expected:{mime:string;sha256:string;sizeBytes:number}){try{const out=await this.client.send(new HeadObjectCommand({Bucket:this.bucket,Key:key}));if(Number(out.ContentLength??-1)!==expected.sizeBytes)throw new Error("stored object size mismatch");if((out.ContentType??"").split(";")[0]!==expected.mime)throw new Error("stored object content type mismatch");if((out.Metadata?.sha256??"").toLowerCase()!==expected.sha256.toLowerCase())throw new Error("stored object sha256 metadata mismatch");return out.VersionId??null;}catch(error){throw new ServiceUnavailableException({code:"UPLOAD_HANDOFF_VERIFICATION_FAILED",message:"Uploaded object did not match the authorized handoff"},{cause:error});}}
  async remove(key:string){try{await this.client.send(new DeleteObjectCommand({Bucket:this.bucket,Key:key}));}catch{/* lifecycle cleanup is secondary control */}}
}
