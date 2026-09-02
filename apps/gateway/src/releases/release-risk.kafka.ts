import { Injectable, OnModuleDestroy, OnModuleInit } from "@nestjs/common";
import { Kafka, type Consumer, type Producer } from "kafkajs";
import { Subject } from "rxjs";
import type { ReleaseRiskEventEnvelope } from "./releases.dto";
@Injectable()
export class ReleaseRiskKafkaPublisher implements OnModuleInit, OnModuleDestroy {
  private readonly kafka:Kafka; private readonly producer:Producer; private readonly consumer:Consumer; private connected=false; private consumerConnected=false;
  readonly events$=new Subject<ReleaseRiskEventEnvelope>();
  constructor(){const brokers=(process.env.KAFKA_BROKERS??"kafka:9092").split(",").map(x=>x.trim()).filter(Boolean);this.kafka=new Kafka({clientId:process.env.KAFKA_CLIENT_ID??"verideploy-gateway",brokers});this.producer=this.kafka.producer({allowAutoTopicCreation:false});const instance=process.env.INSTANCE_ID??process.env.HOSTNAME??"local";this.consumer=this.kafka.consumer({groupId:`verideploy-gateway-release-risk-events-v1-${instance}`});}
  async onModuleInit(){if(process.env.DISABLE_KAFKA_CONSUMER==="true")return;await this.consumer.connect();this.consumerConnected=true;await this.consumer.subscribe({topic:"verideploy.events.release-risk.v1",fromBeginning:false});await this.consumer.run({eachMessage:async({message})=>{if(!message.value)return;try{const event=JSON.parse(message.value.toString("utf8")) as ReleaseRiskEventEnvelope;if(event?.event_type&&event?.payload)this.events$.next(event);}catch{}}});}
  private async ensureConnected(){if(!this.connected){await this.producer.connect();this.connected=true;}}
  async publish(command:Record<string,unknown>){await this.ensureConnected();await this.producer.send({topic:"verideploy.commands.release-risk.v1",acks:-1,messages:[{key:String(command.assessment_id),value:JSON.stringify(command),headers:{"schema-version":"1.0","correlation-id":String(command.correlation_id)}}]});}
  async onModuleDestroy(){this.events$.complete();if(this.consumerConnected)await this.consumer.disconnect();if(this.connected)await this.producer.disconnect();}
}
