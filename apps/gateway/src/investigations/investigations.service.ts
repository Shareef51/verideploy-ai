import { Injectable, NotFoundException, ServiceUnavailableException } from "@nestjs/common";
import { createHash } from "node:crypto";
import type { CancelInvestigationRequest, CreateInvestigationRequest, InvestigationEventEnvelope } from "./investigations.dto";
import { InvestigationKafkaBridge } from "./investigation.kafka";
import { PrivateAiClient } from "../boundary/private-ai.client";

function stableUuid(tenantId: string, idempotencyKey: string): string {
  const digest = createHash("sha256").update(`${tenantId}:investigation:${idempotencyKey}`).digest();
  const bytes = Buffer.from(digest.subarray(0, 16));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x50; bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const h = bytes.toString("hex");
  return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
}

@Injectable()
export class InvestigationsService {
  constructor(readonly kafka: InvestigationKafkaBridge, private readonly ai:PrivateAiClient) {}

  async create(input: CreateInvestigationRequest, tenantId: string, userId: string, idempotencyKey: string, correlationId: string) {
    const investigationId = stableUuid(tenantId, idempotencyKey);
    const command = {
      investigation_id: investigationId, tenant_id: tenantId, requested_by: userId, correlation_id: correlationId,
      idempotency_key: idempotencyKey, query: input.query, workflow_type: "incident_investigation", incident_id: input.incident_id ?? null,
    };
    try { await this.kafka.publishCreate(command); }
    catch (error) { throw new ServiceUnavailableException({ code: "KAFKA_UNAVAILABLE", message: "Investigation command could not be durably queued" }, { cause: error }); }
    return { investigation_id: investigationId, correlation_id: correlationId, status: "QUEUED", authoritative: false };
  }

  async cancel(id: string, body: CancelInvestigationRequest, tenantId: string, userId: string, correlationId: string) {
    try {
      await this.kafka.publishCancel({ investigation_id: id, tenant_id: tenantId, requested_by: userId, correlation_id: correlationId, reason: body.reason });
    } catch (error) {
      throw new ServiceUnavailableException({ code: "KAFKA_UNAVAILABLE", message: "Cancellation command could not be durably queued" }, { cause: error });
    }
    return { investigation_id: id, status: "CANCELLING", authoritative: false };
  }


  async list(tenantId: string, correlationId: string) {
    const response = await this.ai.request("/internal/v1/investigations",tenantId,correlationId); return response;
  }


  async page(tenantId:string,correlationId:string,limit:number,cursor?:string){const q=new URLSearchParams({limit:String(limit)});if(cursor)q.set("cursor",cursor);return this.ai.request(`/internal/v1/investigations/page?${q}`,tenantId,correlationId);}

  async view(id: string, tenantId: string, correlationId: string) {
    const response = await this.ai.request(`/internal/v1/investigations/${encodeURIComponent(id)}/view`,tenantId,correlationId);
    if (response.statusCode === 404) throw new NotFoundException("investigation not found");
    return response;
  }

  async get(id: string, tenantId: string, correlationId: string) {
    const response = await this.ai.request(`/internal/v1/investigations/${encodeURIComponent(id)}`,tenantId,correlationId);
    if (response.statusCode === 404) throw new NotFoundException("investigation not found"); return response;
  }

  async events(id: string, tenantId: string, correlationId: string, afterSequence: number): Promise<InvestigationEventEnvelope[]> {
    const response = await this.ai.request<InvestigationEventEnvelope[]>(`/internal/v1/investigations/${encodeURIComponent(id)}/events?after_sequence=${afterSequence}&limit=500`,tenantId,correlationId);
    if(response.statusCode===404) throw new NotFoundException("investigation not found"); if(response.statusCode>=400) throw new ServiceUnavailableException("event replay unavailable"); return response.body;
  }
}
