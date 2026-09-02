import { Controller, Get, ServiceUnavailableException } from "@nestjs/common";
import * as http from "node:http";
import * as https from "node:https";

const VERSION = "0.75.0";

function probeUrl(url: string, timeoutMs = 1500): Promise<boolean> {
  return new Promise((resolve) => {
    try {
      const parsed = new URL(url);
      const transport = parsed.protocol === "https:" ? https : http;
      const request = transport.request(parsed, { method: "GET", timeout: timeoutMs }, (response) => {
        response.resume();
        resolve(Boolean(response.statusCode && response.statusCode >= 200 && response.statusCode < 300));
      });
      request.on("timeout", () => { request.destroy(); resolve(false); });
      request.on("error", () => resolve(false));
      request.end();
    } catch {
      resolve(false);
    }
  });
}

@Controller("health")
export class HealthController {
  @Get("live")
  live() {
    return { status: "ok", service: "verideploy-gateway", version: VERSION, timestamp: new Date().toISOString() };
  }

  @Get("ready")
  async ready() {
    const aiBase = process.env.AI_SERVICE_BASE_URL;
    const issuer = process.env.OIDC_ISSUER_URL;
    const configured = Boolean(aiBase && process.env.KAFKA_BROKERS && (issuer || process.env.GATEWAY_DEV_AUTH_BYPASS === "true"));
    const deep = process.env.PLATFORM_DEPENDENCY_READINESS_ENABLED === "true";
    const aiReady = !deep || Boolean(aiBase && await probeUrl(`${aiBase.replace(/\/$/, "")}/health/ready`));
    const identityReady = !deep || Boolean(issuer && await probeUrl(`${issuer.replace(/\/$/, "")}/.well-known/openid-configuration`));
    const required = { configuration: configured, ai_service: aiReady, identity: identityReady };
    const checks = Object.fromEntries(Object.entries(required).map(([name, ok]) => [name, ok ? "ok" : "failed"]));
    if (Object.values(required).some((ok) => !ok)) {
      throw new ServiceUnavailableException({
        status: "degraded",
        service: "verideploy-gateway",
        version: VERSION,
        checks,
        timestamp: new Date().toISOString(),
      });
    }
    return { status: "ready", service: "verideploy-gateway", version: VERSION, checks, timestamp: new Date().toISOString() };
  }
}
