import "./observability/telemetry";
import { NestFactory } from "@nestjs/core";
import { AppModule } from "./app.module";
import { CorrelationIdMiddleware } from "./observability/correlation.middleware";
import { ApiExceptionFilter } from "./boundary/api-exception.filter";
import { WsAdapter } from "./events/ws-adapter";
import { loadGatewayConfig } from "./config/environment";
async function bootstrap(){const config=loadGatewayConfig();const app=await NestFactory.create(AppModule,{bufferLogs:true});app.setGlobalPrefix("api/v1");app.use(new CorrelationIdMiddleware().use);app.useGlobalFilters(new ApiExceptionFilter());app.useWebSocketAdapter(new WsAdapter(app));app.enableShutdownHooks();await app.listen(config.port,"0.0.0.0");}
bootstrap().catch((error)=>{console.error(error);process.exitCode=1;});
