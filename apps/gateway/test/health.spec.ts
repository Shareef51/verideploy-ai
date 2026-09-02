import { Test } from "@nestjs/testing";
import { HealthController } from "../src/health/health.controller";

describe("HealthController", () => {
  beforeEach(() => {
    process.env.AI_SERVICE_BASE_URL = "http://ai-service:8000";
    process.env.KAFKA_BROKERS = "kafka:9092";
    process.env.GATEWAY_DEV_AUTH_BYPASS = "true";
    process.env.PLATFORM_DEPENDENCY_READINESS_ENABLED = "false";
  });

  it("reports liveness", async () => {
    const m = await Test.createTestingModule({ controllers: [HealthController] }).compile();
    expect(m.get(HealthController).live().status).toBe("ok");
  });

  it("reports readiness with foundational configuration", async () => {
    const m = await Test.createTestingModule({ controllers: [HealthController] }).compile();
    expect((await m.get(HealthController).ready()).status).toBe("ready");
  });
});
