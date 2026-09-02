import { BadRequestException, Body, Controller, Get, Headers, MessageEvent, Param, Post, Query, Res, Sse } from "@nestjs/common";
import { Response } from "express";
import { concat, from, map, merge, Observable, of, filter, distinct } from "rxjs";
import type { CancelInvestigationRequest, CreateInvestigationRequest, InvestigationEventEnvelope } from "./investigations.dto";
import { InvestigationsService } from "./investigations.service";

function required(value: string | undefined, name: string): string { if (!value) throw new BadRequestException(`${name} header is required`); return value; }

@Controller("investigations")
export class InvestigationsController {
  constructor(private readonly service: InvestigationsService) {}

  @Post()
  create(@Body() body: CreateInvestigationRequest, @Headers("x-tenant-id") tenant?: string, @Headers("x-user-id") user?: string, @Headers("idempotency-key") key?: string, @Headers("x-correlation-id") correlation?: string) {
    return this.service.create(body, required(tenant,"x-tenant-id"), required(user,"x-user-id"), required(key,"idempotency-key"), required(correlation,"x-correlation-id"));
  }

  @Get()
  async list(@Headers("x-tenant-id") tenant?: string, @Headers("x-correlation-id") correlation?: string, @Res() res?: Response) {
    const result = await this.service.list(required(tenant,"x-tenant-id"), required(correlation,"x-correlation-id")); return res!.status(result.statusCode).json(result.body);
  }


  @Get("page")
  async page(@Headers("x-tenant-id") tenant?:string,@Headers("x-correlation-id") correlation?:string,@Query("limit") limitRaw?:string,@Query("cursor") cursor?:string,@Res() res?:Response){
    const limit=limitRaw===undefined?25:Number(limitRaw); if(!Number.isInteger(limit)||limit<1||limit>100) throw new BadRequestException("limit must be between 1 and 100");
    const result=await this.service.page(required(tenant,"x-tenant-id"),required(correlation,"x-correlation-id"),limit,cursor);return res!.status(result.statusCode).json(result.body);
  }

  @Get(":id/view")
  async view(@Param("id") id: string, @Headers("x-tenant-id") tenant?: string, @Headers("x-correlation-id") correlation?: string, @Res() res?: Response) {
    const result = await this.service.view(id, required(tenant,"x-tenant-id"), required(correlation,"x-correlation-id")); return res!.status(result.statusCode).json(result.body);
  }

  @Get(":id")
  async get(@Param("id") id: string, @Headers("x-tenant-id") tenant?: string, @Headers("x-correlation-id") correlation?: string, @Res() res?: Response) {
    const result = await this.service.get(id, required(tenant,"x-tenant-id"), required(correlation,"x-correlation-id")); return res!.status(result.statusCode).json(result.body);
  }

  @Get(":id/events")
  events(@Param("id") id: string, @Headers("x-tenant-id") tenant?: string, @Headers("x-correlation-id") correlation?: string, @Query("after_sequence") afterRaw?: string) {
    const parsed = afterRaw === undefined ? 0 : Number(afterRaw);
    if (!Number.isInteger(parsed) || parsed < 0) throw new BadRequestException("after_sequence must be a non-negative integer");
    return this.service.events(id, required(tenant,"x-tenant-id"), required(correlation,"x-correlation-id"), parsed);
  }

  @Post(":id/cancel")
  cancel(@Param("id") id: string, @Body() body: CancelInvestigationRequest, @Headers("x-tenant-id") tenant?: string, @Headers("x-user-id") user?: string, @Headers("x-correlation-id") correlation?: string) {
    return this.service.cancel(id, body, required(tenant,"x-tenant-id"), required(user,"x-user-id"), required(correlation,"x-correlation-id"));
  }

  @Sse(":id/stream")
  stream(@Param("id") id: string, @Headers("x-tenant-id") tenant?: string, @Headers("x-correlation-id") correlation?: string, @Headers("last-event-id") lastEventId?: string): Observable<MessageEvent> {
    const tenantId = required(tenant,"x-tenant-id"); const correlationId = required(correlation,"x-correlation-id");
    const after = Number.isFinite(Number(lastEventId)) ? Number(lastEventId) : 0;
    const replay$ = from(this.service.events(id, tenantId, correlationId, after));
    const historical$ = replay$.pipe(map((events) => events.map(toMessage)), map((events) => events));
    const live$ = this.service.kafka.events$.pipe(filter((event) => event.tenant_id === tenantId && event.investigation_id === id), map(toMessage));
    return concat(historical$.pipe(map((items) => ({ data: items, type: "replay" } as MessageEvent))), merge(live$, of({ data: { heartbeat: true }, type: "heartbeat" } as MessageEvent))).pipe(distinct((event) => String(event.id ?? JSON.stringify(event.data))));
  }
}

function toMessage(event: InvestigationEventEnvelope): MessageEvent {
  return { id: String(event.sequence_number), type: event.event_type, data: event };
}
