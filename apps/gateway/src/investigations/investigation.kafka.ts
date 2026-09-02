import { Injectable, OnModuleDestroy, OnModuleInit } from "@nestjs/common";
import { Kafka, type Consumer, type Producer } from "kafkajs";
import { Subject } from "rxjs";
import type { InvestigationEventEnvelope } from "./investigations.dto";

@Injectable()
export class InvestigationKafkaBridge implements OnModuleInit, OnModuleDestroy {
  private readonly kafka: Kafka;
  private readonly producer: Producer;
  private readonly consumer: Consumer;
  private producerConnected = false;
  private consumerConnected = false;
  readonly events$ = new Subject<InvestigationEventEnvelope>();

  constructor() {
    const brokers = (process.env.KAFKA_BROKERS ?? "kafka:9092").split(",").map((v) => v.trim()).filter(Boolean);
    this.kafka = new Kafka({ clientId: process.env.KAFKA_CLIENT_ID ?? "verideploy-gateway", brokers });
    this.producer = this.kafka.producer({ allowAutoTopicCreation: false });
    const instanceId = process.env.INSTANCE_ID ?? process.env.HOSTNAME ?? "local";
    this.consumer = this.kafka.consumer({ groupId: `verideploy-gateway-investigation-events-v1-${instanceId}` });
  }

  async onModuleInit(): Promise<void> {
    if (process.env.DISABLE_KAFKA_CONSUMER === "true") return;
    await this.consumer.connect(); this.consumerConnected = true;
    await this.consumer.subscribe({ topic: "verideploy.events.investigation.v1", fromBeginning: false });
    await this.consumer.run({
      eachMessage: async ({ message }) => {
        if (!message.value) return;
        try {
          const event = JSON.parse(message.value.toString("utf8")) as InvestigationEventEnvelope;
          if (event.event_id && event.investigation_id && Number.isInteger(event.sequence_number)) this.events$.next(event);
        } catch {
          // Invalid event payloads are ignored here and remain visible to Kafka operational tooling.
        }
      },
    });
  }

  private async ensureProducer(): Promise<void> {
    if (!this.producerConnected) { await this.producer.connect(); this.producerConnected = true; }
  }

  async publishCreate(command: Record<string, unknown>): Promise<void> {
    await this.ensureProducer();
    await this.producer.send({
      topic: "verideploy.commands.investigation.v1", acks: -1,
      messages: [{ key: String(command.investigation_id), value: JSON.stringify(command), headers: { "schema-version": "1.0", "correlation-id": String(command.correlation_id) } }],
    });
  }

  async publishCancel(command: Record<string, unknown>): Promise<void> {
    await this.ensureProducer();
    await this.producer.send({
      topic: "verideploy.commands.investigation-cancel.v1", acks: -1,
      messages: [{ key: String(command.investigation_id), value: JSON.stringify(command), headers: { "schema-version": "1.0", "correlation-id": String(command.correlation_id) } }],
    });
  }

  async onModuleDestroy(): Promise<void> {
    this.events$.complete();
    if (this.consumerConnected) await this.consumer.disconnect();
    if (this.producerConnected) await this.producer.disconnect();
  }
}
