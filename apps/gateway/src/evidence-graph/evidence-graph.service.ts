import { Injectable } from "@nestjs/common";
import { PrivateAiClient } from "../boundary/private-ai.client";
@Injectable()
export class EvidenceGraphService{
  constructor(private readonly ai:PrivateAiClient){}
  snapshot(t:string,c:string){return this.ai.request("/internal/v1/evidence-graph/snapshot",t,c);}
  path(t:string,c:string,source:string,target:string,maxDepth:number){const q=new URLSearchParams({source_entity_id:source,target_entity_id:target,max_depth:String(maxDepth)});return this.ai.request(`/internal/v1/evidence-graph/path?${q}`,t,c);}
}
