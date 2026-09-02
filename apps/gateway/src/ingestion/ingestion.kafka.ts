import { Injectable, OnModuleDestroy, OnModuleInit } from "@nestjs/common";
import { Kafka, Producer } from "kafkajs";
@Injectable()
export class IngestionKafkaBridge implements OnModuleInit,OnModuleDestroy {
  private readonly producer:Producer; private connected=false;
  constructor(){ const brokers=(process.env.KAFKA_BROKERS??"kafka:9092").split(","); this.producer=new Kafka({clientId:process.env.KAFKA_CLIENT_ID??"verideploy-gateway",brokers}).producer({allowAutoTopicCreation:false}); }
  async onModuleInit(){await this.producer.connect();this.connected=true;} async onModuleDestroy(){if(this.connected)await this.producer.disconnect();}
  async publish(command:Record<string,unknown>){await this.producer.send({topic:"verideploy.commands.ingestion.v1",messages:[{key:String(command.job_id),value:JSON.stringify(command),headers:{"schema-version":"1.0"}}]});}
}
