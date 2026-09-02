import { Module } from "@nestjs/common";
import { BoundaryModule } from "../boundary/boundary.module";
import { EvaluationsController } from "./evaluations.controller";
import { EvaluationsService } from "./evaluations.service";
@Module({imports:[BoundaryModule],controllers:[EvaluationsController],providers:[EvaluationsService]})
export class EvaluationsModule {}
