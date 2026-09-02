"use client";
import { context, propagation, trace, SpanKind } from "@opentelemetry/api";
import { ZoneContextManager } from "@opentelemetry/context-zone";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { BatchSpanProcessor, WebTracerProvider } from "@opentelemetry/sdk-trace-web";
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION } from "@opentelemetry/semantic-conventions";
let registered=false;
export function registerBrowserTelemetry(){
  if(registered || typeof window==="undefined" || process.env.NEXT_PUBLIC_OTEL_ENABLED==="false") return;
  const provider=new WebTracerProvider({resource:resourceFromAttributes({[ATTR_SERVICE_NAME]:"verideploy-web",[ATTR_SERVICE_VERSION]:"0.50.0","service.namespace":"verideploy"}),spanProcessors:[new BatchSpanProcessor(new OTLPTraceExporter({url:process.env.NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT??"http://localhost:4318/v1/traces"}))]});
  provider.register({contextManager:new ZoneContextManager()}); registered=true;
}
export async function tracedFetch(input:string, init:RequestInit={}):Promise<Response>{
  registerBrowserTelemetry();
  const tracer=trace.getTracer("verideploy-web");
  return tracer.startActiveSpan(`HTTP ${String(init.method??"GET").toUpperCase()}`,{kind:SpanKind.CLIENT,attributes:{"http.request.method":String(init.method??"GET").toUpperCase(),"url.full":input}},async span=>{
    try{const headers=new Headers(init.headers); const carrier:Record<string,string>={}; propagation.inject(context.active(),carrier); Object.entries(carrier).forEach(([k,v])=>headers.set(k,v)); const response=await fetch(input,{...init,headers}); span.setAttribute("http.response.status_code",response.status); return response;}
    catch(error){span.recordException(error as Error); throw error;} finally{span.end();}
  });
}
