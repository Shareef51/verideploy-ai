import { Module } from "@nestjs/common";
import { EventFanoutService } from "./event-fanout.service";
import { EventWebSocketGateway } from "./event-websocket.gateway";

@Module({ providers: [EventFanoutService, EventWebSocketGateway], exports: [EventFanoutService] })
export class EventsModule {}
