import { Module } from "@nestjs/common";
import { ReleaseRiskKafkaPublisher } from "./release-risk.kafka";
import { ReleasesController } from "./releases.controller";
import { ReleasesService } from "./releases.service";

@Module({ controllers: [ReleasesController], providers: [ReleaseRiskKafkaPublisher, ReleasesService] , exports: [ReleasesService] })
export class ReleasesModule {}
