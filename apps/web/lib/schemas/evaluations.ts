import { z } from "zod";
export const EvaluationCaseSchema=z.object({caseId:z.string(),category:z.string(),score:z.number(),passed:z.boolean(),traceId:z.string().nullable(),correlationId:z.string().nullable()});
export const ExperimentRunSchema=z.object({runId:z.string(),label:z.string(),model:z.string(),promptVersion:z.string(),retriever:z.string(),aggregate:z.number(),passedRate:z.number(),createdAt:z.string(),metrics:z.record(z.string(),z.number()),categories:z.record(z.string(),z.number())});
export const EvaluationDashboardSchema=z.object({runs:z.array(ExperimentRunSchema),cases:z.array(EvaluationCaseSchema)});
export type EvaluationDashboard=z.infer<typeof EvaluationDashboardSchema>;
