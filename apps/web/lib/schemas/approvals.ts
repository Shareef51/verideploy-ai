import { z } from "zod";
export const ApprovalSchema=z.object({approval_id:z.string().uuid(),action_type:z.string(),risk:z.string(),risk_score:z.number(),status:z.string(),version:z.number().int().positive(),expires_at:z.string(),delegated_to:z.string().nullable().optional(),evidence_summary:z.object({title:z.string(),summary:z.string(),evidence_ids:z.array(z.string()),citation_ids:z.array(z.string()),risk_factors:z.array(z.string())})});
export const ApprovalListSchema=z.array(ApprovalSchema);
export type Approval=z.infer<typeof ApprovalSchema>;
