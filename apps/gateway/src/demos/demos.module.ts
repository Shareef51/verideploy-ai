import { Module } from "@nestjs/common";
import { DemosController } from "./demos.controller";
import { DemosService } from "./demos.service";
import { ReleasesModule } from "../releases/releases.module";
import { InvestigationsModule } from "../investigations/investigations.module";
import { IngestionModule } from "../ingestion/ingestion.module";
import { ApprovalsModule } from "../approvals/approvals.module";
@Module({imports:[ReleasesModule,InvestigationsModule,IngestionModule,ApprovalsModule],controllers:[DemosController],providers:[DemosService]}) export class DemosModule{}
