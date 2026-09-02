import { NodeSDK } from "@opentelemetry/sdk-node";
import { getNodeAutoInstrumentations } from "@opentelemetry/auto-instrumentations-node";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-grpc";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION, SEMRESATTRS_DEPLOYMENT_ENVIRONMENT } from "@opentelemetry/semantic-conventions";

const enabled=(process.env.OTEL_ENABLED??"true").toLowerCase()!=="false";
if(enabled){
  const sdk=new NodeSDK({
    resource:resourceFromAttributes({
      [ATTR_SERVICE_NAME]:process.env.OTEL_SERVICE_NAME??"verideploy-gateway",
      [ATTR_SERVICE_VERSION]:"0.50.0",
      [SEMRESATTRS_DEPLOYMENT_ENVIRONMENT]:process.env.APP_ENV??"development",
      "service.namespace":"verideploy",
    }),
    traceExporter:new OTLPTraceExporter({url:process.env.OTEL_EXPORTER_OTLP_ENDPOINT??"http://otel-collector:4317"}),
    instrumentations:[getNodeAutoInstrumentations({
      "@opentelemetry/instrumentation-fs":{enabled:false},
      "@opentelemetry/instrumentation-http":{ignoreIncomingRequestHook:(req)=>req.url?.includes("/health/")??false},
    })],
  });
  sdk.start();
  const shutdown=()=>sdk.shutdown().catch(()=>undefined);
  process.once("SIGTERM",shutdown); process.once("SIGINT",shutdown);
}
