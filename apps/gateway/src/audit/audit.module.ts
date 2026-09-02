import { Module } from "@nestjs/common";import { BoundaryModule } from "../boundary/boundary.module";import { AuditController } from "./audit.controller";import { AuditService } from "./audit.service";
@Module({imports:[BoundaryModule],controllers:[AuditController],providers:[AuditService]}) export class AuditModule{}
