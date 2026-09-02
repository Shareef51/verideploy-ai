import { Injectable } from "@nestjs/common";
import { PrivateAiClient } from "../boundary/private-ai.client";
@Injectable() export class AgentExecutionService{constructor(private readonly ai:PrivateAiClient){}
view(runId:string,tenant:string,correlation:string){return this.ai.request(`/internal/v1/graph-runs/${encodeURIComponent(runId)}/execution-view`,tenant,correlation);}
events(runId:string,tenant:string,correlation:string,after:number){return this.ai.request(`/internal/v1/graph-runs/${encodeURIComponent(runId)}/events?after_sequence=${after}`,tenant,correlation);}
}
