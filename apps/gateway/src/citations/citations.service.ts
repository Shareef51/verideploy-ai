import { Injectable } from "@nestjs/common";
import { PrivateAiClient } from "../boundary/private-ai.client";
@Injectable()
export class CitationsService {
  constructor(private readonly ai:PrivateAiClient){}
  preview(tenantId:string,correlationId:string,citationId:string){
    return this.ai.request(`/internal/v1/citations/${encodeURIComponent(citationId)}/preview`,tenantId,correlationId,{headers:{
      "x-retrieval-permissions":process.env.GATEWAY_RETRIEVAL_PERMISSIONS??"retrieval.read,retrieval.preview.read",
      "x-allowed-services":process.env.GATEWAY_ALLOWED_SERVICES??"",
      "x-allowed-environments":process.env.GATEWAY_ALLOWED_ENVIRONMENTS??"",
      "x-allowed-teams":process.env.GATEWAY_ALLOWED_TEAMS??"",
      "x-allowed-document-kinds":process.env.GATEWAY_ALLOWED_DOCUMENT_KINDS??"",
    }});
  }
}
