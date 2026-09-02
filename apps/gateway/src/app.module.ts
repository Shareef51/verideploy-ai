import { DemosModule } from "./demos/demos.module";
import { AuditModule } from "./audit/audit.module";
import { SecurityModule } from "./security/security.module";
import { EvaluationsModule } from "./evaluations/evaluations.module";
import { LLMOpsModule } from "./llmops/llmops.module";
import { AgentExecutionModule } from "./agent-execution/agent-execution.module";
import { Module } from "@nestjs/common";
import { HealthController } from "./health/health.controller";
import { ReleasesModule } from "./releases/releases.module";
import { InvestigationsModule } from "./investigations/investigations.module";
import { IngestionModule } from "./ingestion/ingestion.module";
import { PostmortemsModule } from "./postmortems/postmortems.module";
import { TopologyModule } from "./topology/topology.module";
import { EvidenceGraphModule } from "./evidence-graph/evidence-graph.module";
import { CitationsModule } from "./citations/citations.module";
import { ApprovalsModule } from "./approvals/approvals.module";
import { BoundaryModule } from "./boundary/boundary.module";
import { EventsModule } from "./events/events.module";
@Module({imports:[DemosModule, EventsModule, SecurityModule, BoundaryModule, ReleasesModule, InvestigationsModule, IngestionModule, PostmortemsModule, TopologyModule, EvidenceGraphModule, CitationsModule, ApprovalsModule, AgentExecutionModule, LLMOpsModule, EvaluationsModule, AuditModule],controllers:[HealthController]})
export class AppModule {}
