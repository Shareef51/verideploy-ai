import { Module } from "@nestjs/common";
import { PostmortemsController } from "./postmortems.controller";
import { PostmortemKafkaPublisher } from "./postmortem.kafka";
import { PostmortemsService } from "./postmortems.service";
@Module({controllers:[PostmortemsController],providers:[PostmortemsService,PostmortemKafkaPublisher]}) export class PostmortemsModule{}
