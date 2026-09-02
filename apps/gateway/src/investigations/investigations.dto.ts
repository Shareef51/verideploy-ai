export interface CreateInvestigationRequest {
  query: string;
  incident_id?: string;
}

export interface CancelInvestigationRequest {
  reason: string;
}

export interface InvestigationEventEnvelope {
  event_id: string;
  event_type: string;
  schema_version: string;
  tenant_id: string;
  correlation_id: string;
  investigation_id: string;
  sequence_number: number;
  occurred_at: string;
  producer: string;
  trace_context: Record<string, string>;
  payload: Record<string, unknown>;
}
