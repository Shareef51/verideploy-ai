import { Module } from "@nestjs/common";
import { InvestigationKafkaBridge } from "./investigation.kafka";
import { InvestigationsController } from "./investigations.controller";
import { InvestigationsService } from "./investigations.service";

@Module({ controllers: [InvestigationsController], providers: [InvestigationKafkaBridge, InvestigationsService], exports: [InvestigationKafkaBridge, InvestigationsService] })
export class InvestigationsModule {}
