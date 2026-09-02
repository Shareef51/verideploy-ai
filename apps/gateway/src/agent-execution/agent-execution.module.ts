import { Module } from "@nestjs/common";
import { BoundaryModule } from "../boundary/boundary.module";
import { AgentExecutionController } from "./agent-execution.controller";
import { AgentExecutionService } from "./agent-execution.service";
@Module({imports:[BoundaryModule],controllers:[AgentExecutionController],providers:[AgentExecutionService]}) export class AgentExecutionModule{}
