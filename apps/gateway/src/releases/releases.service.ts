import { Injectable, ServiceUnavailableException } from "@nestjs/common";
import { PrivateAiClient } from "../boundary/private-ai.client";
import { createHash, randomUUID } from "node:crypto";
import type { CreateReleaseRiskRequest } from "./releases.dto";
import { ReleaseRiskKafkaPublisher } from "./release-risk.kafka";

function stableAssessmentId(tenantId: string, idempotencyKey: string): string {
  const digest = createHash("sha256").update(`${tenantId}:${idempotencyKey}`).digest();
  const bytes = Buffer.from(digest.subarray(0, 16));
  bytes[6] = (bytes[6] ?? 0) & 0x0f | 0x50;
  bytes[8] = (bytes[8] ?? 0) & 0x3f | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}

@Injectable()
export class ReleasesService {
  constructor(private readonly publisher: ReleaseRiskKafkaPublisher, private readonly ai:PrivateAiClient) {}

  async createRiskAssessment(input: CreateReleaseRiskRequest, tenantId: string, userId: string, idempotencyKey: string, correlationId: string) {
    const assessmentId = stableAssessmentId(tenantId, idempotencyKey);
    const command = {
      assessment_id: assessmentId,
      tenant_id: tenantId,
      requested_by: userId,
      correlation_id: correlationId,
      idempotency_key: idempotencyKey,
      repository: input.repository,
      release_id: input.release_id,
      commit_sha: input.commit_sha,
      target_environment: input.target_environment ?? "production",
      changed_file_details: input.changed_file_details ?? [],
      policy: {
        failed_workflows: 0,
        database_migration_changed: false,
        rollback_plan_verified: true,
        production_incidents_last_30d: 0,
        high_severity_incidents_last_30d: 0,
        test_coverage_delta_percent: 0,
        security_scan_critical_findings: 0,
        deployment_window_risk: 0,
        ...input.policy,
      },
    };
    try {
      await this.publisher.publish(command);
      const now = new Date().toISOString();
      return { assessment_id: assessmentId, tenant_id: tenantId, requested_by: userId, correlation_id: correlationId, idempotency_key: idempotencyKey, repository: input.repository, release_id: input.release_id, commit_sha: input.commit_sha, target_environment: input.target_environment ?? "production", status: "QUEUED", policy_input: command.policy, changed_file_details: input.changed_file_details ?? [], result: null, error_code: null, error_message: null, created_at: now, updated_at: now, version: 1 };
    } catch (error) {
      throw new ServiceUnavailableException({ code: "KAFKA_UNAVAILABLE", message: "Release risk command could not be durably queued", request_id: randomUUID() }, { cause: error });
    }
  }

  async getRiskAssessment(assessmentId: string, tenantId: string, correlationId: string) {
    return this.ai.request(`/internal/v1/releases/assessments/${encodeURIComponent(assessmentId)}`,tenantId,correlationId);
  }

  async listRiskAssessments(tenantId:string, correlationId:string, limit=50){
    return this.ai.request(`/internal/v1/releases/assessments?limit=${Math.max(1,Math.min(100,limit))}`,tenantId,correlationId);
  }

  get events$(){ return this.publisher.events$; }
}
