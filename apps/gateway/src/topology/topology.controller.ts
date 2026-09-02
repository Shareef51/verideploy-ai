import { Controller, Get, Headers, HttpException } from "@nestjs/common";
import { TopologyService } from "./topology.service";

function requireHeader(value: string | undefined, name: string): string {
  if (!value?.trim()) throw new HttpException(`${name} header is required`, 400);
  return value.trim();
}

@Controller("topology")
export class TopologyController {
  constructor(private readonly topology: TopologyService) {}

  @Get("nexuspay")
  async nexuspay(@Headers("x-tenant-id") tenantId?: string, @Headers("x-correlation-id") correlationId?: string) {
    const result = await this.topology.getNexusPay(
      requireHeader(tenantId, "x-tenant-id"),
      correlationId?.trim() || crypto.randomUUID(),
    );
    if (result.statusCode >= 400) throw new HttpException(result.body as Record<string, any>, result.statusCode);
    return result.body;
  }
}
