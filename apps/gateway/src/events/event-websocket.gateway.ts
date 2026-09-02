import { OnGatewayConnection, OnGatewayDisconnect, WebSocketGateway, WebSocketServer } from "@nestjs/websockets";
import type { Server, WebSocket } from "ws";
import { Subscription } from "rxjs";
import { EventFanoutService } from "./event-fanout.service";

interface AuthenticatedSocket extends WebSocket {
  verideployTenantId?: string;
  verideploySubscription?: Subscription;
}

@WebSocketGateway({ path: "/ws/events", cors: false })
export class EventWebSocketGateway implements OnGatewayConnection, OnGatewayDisconnect {
  @WebSocketServer() server!: Server;

  constructor(private readonly fanout: EventFanoutService) {}

  handleConnection(client: AuthenticatedSocket, request: { headers?: Record<string, string | string[] | undefined> }): void {
    const tenantHeader = request.headers?.["x-authenticated-tenant-id"];
    const tenantId = Array.isArray(tenantHeader) ? tenantHeader[0] : tenantHeader;
    if (!tenantId) {
      client.close(1008, "authenticated tenant required");
      return;
    }
    client.verideployTenantId = tenantId;
    client.verideploySubscription = this.fanout.stream(`tenant:${tenantId}`).subscribe((event) => {
      if (event.tenant_id !== tenantId || client.readyState !== client.OPEN) return;
      client.send(JSON.stringify(event));
    });
  }

  handleDisconnect(client: AuthenticatedSocket): void {
    client.verideploySubscription?.unsubscribe();
  }
}
