import { Injectable, OnModuleDestroy, OnModuleInit } from "@nestjs/common";
import { createClient, type RedisClientType } from "redis";
import { Subject } from "rxjs";

export interface FanoutEnvelope {
  event_id: string;
  event_type: string;
  tenant_id: string;
  aggregate_id: string;
  ordering_key: string;
  sequence_number: number;
  correlation_id: string;
  schema_version: string;
  payload: unknown;
}

@Injectable()
export class EventFanoutService implements OnModuleInit, OnModuleDestroy {
  private readonly publisher: RedisClientType;
  private readonly subscriber: RedisClientType;
  private readonly events = new Map<string, Subject<FanoutEnvelope>>();

  constructor() {
    const url = process.env.REDIS_URL ?? "redis://redis:6379/0";
    this.publisher = createClient({ url });
    this.subscriber = this.publisher.duplicate();
  }

  async onModuleInit(): Promise<void> {
    if (process.env.DISABLE_REDIS_FANOUT === "true") return;
    await Promise.all([this.publisher.connect(), this.subscriber.connect()]);
    await this.subscriber.pSubscribe("verideploy:events:*", (message, channel) => {
      try {
        const event = JSON.parse(message) as FanoutEnvelope;
        const tenantChannel = `tenant:${event.tenant_id}`;
        this.events.get(tenantChannel)?.next(event);
        this.events.get(channel)?.next(event);
      } catch {
        // Malformed Redis fan-out payloads are discarded; Kafka remains authoritative.
      }
    });
  }

  stream(channel: string): Subject<FanoutEnvelope> {
    let subject = this.events.get(channel);
    if (!subject) {
      subject = new Subject<FanoutEnvelope>();
      this.events.set(channel, subject);
    }
    return subject;
  }

  async publish(event: FanoutEnvelope): Promise<void> {
    const channel = `verideploy:events:${event.tenant_id}`;
    await this.publisher.publish(channel, JSON.stringify(event));
  }

  async onModuleDestroy(): Promise<void> {
    for (const subject of this.events.values()) subject.complete();
    if (this.subscriber.isOpen) await this.subscriber.quit();
    if (this.publisher.isOpen) await this.publisher.quit();
  }
}
