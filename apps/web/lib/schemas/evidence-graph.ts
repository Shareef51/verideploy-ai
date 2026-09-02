import { z } from "zod";
const Entity=z.object({entity_id:z.string(),entity_type:z.string(),label:z.string(),natural_key:z.string(),observed_at:z.string().nullable().optional()});
const Edge=z.object({edge_id:z.string(),source_entity_id:z.string(),target_entity_id:z.string(),relationship:z.string(),confidence:z.number(),occurred_at:z.string().nullable().optional()});
export const EvidenceGraphSnapshotSchema=z.object({entities:z.array(Entity),edges:z.array(Edge),snapshot_sha256:z.string()});
export type EvidenceGraphSnapshot=z.infer<typeof EvidenceGraphSnapshotSchema>;
