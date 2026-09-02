import { Module } from "@nestjs/common";
import { CitationsController } from "./citations.controller";
import { CitationsService } from "./citations.service";
@Module({controllers:[CitationsController],providers:[CitationsService]})
export class CitationsModule{}
