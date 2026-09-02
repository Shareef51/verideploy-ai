import { Injectable, OnModuleDestroy } from "@nestjs/common";
import { Kafka, type Producer } from "kafkajs";

@Injectable()
export class PostmortemKafkaPublisher implements OnModuleDestroy {
  private readonly producer: Producer;
  private connected=false;
  constructor(){
    const brokers=(process.env.KAFKA_BROKERS??"kafka:9092").split(",").map(v=>v.trim()).filter(Boolean);
    this.producer=new Kafka({clientId:process.env.KAFKA_CLIENT_ID??"verideploy-gateway",brokers}).producer({allowAutoTopicCreation:false});
  }
  private async ensure(){ if(!this.connected){ await this.producer.connect(); this.connected=true; } }
  async publish(command: Record<string,unknown>){ await this.ensure(); await this.producer.send({topic:"verideploy.commands.postmortem.v1",acks:-1,messages:[{key:String(command.postmortem_id),value:JSON.stringify(command),headers:{"schema-version":"1.0","correlation-id":String(command.correlation_id)}}]}); }
  async onModuleDestroy(){ if(this.connected) await this.producer.disconnect(); }
}
