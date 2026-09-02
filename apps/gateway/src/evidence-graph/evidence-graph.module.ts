import { Module } from "@nestjs/common";
import { EvidenceGraphController } from "./evidence-graph.controller";
import { EvidenceGraphService } from "./evidence-graph.service";
@Module({controllers:[EvidenceGraphController],providers:[EvidenceGraphService]})
export class EvidenceGraphModule{}
