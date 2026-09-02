export type CreatePostmortemRequest = {
  investigation_id: string;
  title: string;
  reviewed_evidence: Record<string, unknown>;
};
export type ReviewPostmortemRequest = { decision: "APPROVE"|"REQUEST_CHANGES"|"REJECT"; notes: string; expected_version: number; };
