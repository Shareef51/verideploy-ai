import { Injectable } from "@nestjs/common";
import { PrivateAiClient } from "../boundary/private-ai.client";
@Injectable()
export class LLMOpsService { constructor(private readonly ai: PrivateAiClient) {}
  trace(tenantId:string,correlationId:string,requestCorrelationId:string){ return this.ai.get(`/internal/v1/llmops/correlations/${encodeURIComponent(correlationId)}`,{tenantId,correlationId:requestCorrelationId}); }
}
