import { Injectable } from "@nestjs/common";
import { PrivateAiClient } from "../boundary/private-ai.client";
@Injectable()
export class TopologyService {
  constructor(private readonly ai:PrivateAiClient){}
  getNexusPay(tenantId:string,correlationId:string){return this.ai.request("/internal/v1/topology/nexuspay",tenantId,correlationId);}
}
