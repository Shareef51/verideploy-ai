import { Injectable, ServiceUnavailableException } from "@nestjs/common";
import { createHmac } from "node:crypto";

export interface PrivateAiResponse<T=unknown>{statusCode:number;body:T;requestId:string|null;}
export interface PrivateAiRequestOptions{method?:"GET"|"POST"|"PUT"|"PATCH"|"DELETE";body?:unknown;headers?:Record<string,string>;timeoutMs?:number;retry?:boolean;}

function canonical(method:string,path:string,tenantId:string,correlationId:string,timestamp:string,body:string){return [method.toUpperCase(),path,tenantId,correlationId,timestamp,body].join("\n");}

@Injectable()
export class PrivateAiClient{
  private readonly baseUrl=process.env.AI_SERVICE_BASE_URL??"http://ai-service:8000";
  private readonly serviceName="verideploy-gateway";
  private readonly secret=(()=>{try{const m=JSON.parse(process.env.INTERNAL_SERVICE_AUTH_SECRETS_JSON??"{}");return m[this.serviceName]??process.env.INTERNAL_SERVICE_AUTH_SECRET??process.env.APP_SECRET_KEY??"local-development-only";}catch{return process.env.INTERNAL_SERVICE_AUTH_SECRET??process.env.APP_SECRET_KEY??"local-development-only";}})();
  private readonly defaultTimeoutMs=Number(process.env.AI_SERVICE_TIMEOUT_MS??5000);
  private readonly maxAttempts=Math.max(1,Math.min(3,Number(process.env.AI_SERVICE_MAX_ATTEMPTS??2)));

  private signedHeaders(method:string,path:string,tenantId:string,correlationId:string,body:string,extra:Record<string,string>={}){
    const timestamp=Math.floor(Date.now()/1000).toString();
    const signature=createHmac("sha256",this.secret).update(canonical(method,path,tenantId,correlationId,timestamp,body)).digest("hex");
    return {"x-internal-service":this.serviceName,"x-tenant-id":tenantId,"x-correlation-id":correlationId,"x-service-auth-timestamp":timestamp,"x-service-auth-signature":signature,...extra};
  }

  async get<T=unknown>(path:string,context:{tenantId:string;correlationId:string}):Promise<PrivateAiResponse<T>>{
    return this.request<T>(path,context.tenantId,context.correlationId,{method:"GET"});
  }

  async request<T=unknown>(path:string,tenantId:string,correlationId:string,options:PrivateAiRequestOptions={}):Promise<PrivateAiResponse<T>>{
    if(!path.startsWith("/internal/v1/")) throw new Error("PrivateAiClient only permits /internal/v1 routes");
    const method=options.method??"GET"; const body=options.body===undefined?"":JSON.stringify(options.body);
    const attempts=options.retry===false?1:this.maxAttempts;
    let lastError:unknown;
    for(let attempt=1;attempt<=attempts;attempt++){
      try{
        const response=await fetch(`${this.baseUrl}${path}`,{method,headers:this.signedHeaders(method,path,tenantId,correlationId,body,{...(body?{"content-type":"application/json"}:{}),...(options.headers??{})}),body:body||null,cache:"no-store",signal:AbortSignal.timeout(options.timeoutMs??this.defaultTimeoutMs)});
        let parsed:unknown; const text=await response.text(); try{parsed=text?JSON.parse(text):null;}catch{parsed={code:"AI_SERVICE_INVALID_RESPONSE",message:"Private AI service returned non-JSON data"};}
        const requestId=response.headers.get("x-request-id")??response.headers.get("x-correlation-id");
        if(response.status>=500 && attempt<attempts) continue;
        return {statusCode:response.status,body:parsed as T,requestId};
      }catch(error){lastError=error;if(attempt<attempts) continue;}
    }
    throw new ServiceUnavailableException({code:"AI_SERVICE_UNAVAILABLE",message:"Private AI service is temporarily unavailable",correlation_id:correlationId},{cause:lastError});
  }
}
