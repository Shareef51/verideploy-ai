import { AbstractWsAdapter } from "@nestjs/websockets";
import type { MessageMappingProperties } from "@nestjs/websockets";
import { WebSocketServer, type WebSocket } from "ws";
import type { Server as HttpServer } from "node:http";
import { EMPTY, Observable, fromEvent } from "rxjs";
import { filter, mergeMap } from "rxjs/operators";

// @nestjs/websockets defaults to a socket.io-based adapter, but this gateway is written
// against the raw "ws" library (see event-websocket.gateway.ts) and socket.io isn't a
// dependency here. NestJS doesn't ship a concrete ws-library adapter itself (only the
// abstract base class), so this is the standard minimal implementation.
export class WsAdapter extends AbstractWsAdapter {
  create(port: number, options: Record<string, unknown> = {}): WebSocketServer {
    const server = this.httpServer as HttpServer | undefined;
    return new WebSocketServer(server ? { server, ...options } : { port, ...options });
  }

  bindMessageHandlers(
    client: WebSocket,
    handlers: MessageMappingProperties[],
    transform: (data: unknown) => Observable<unknown>,
  ): void {
    fromEvent(client, "message")
      .pipe(
        mergeMap((buffer: unknown) => this.bindMessageHandler(buffer as { data?: unknown }, handlers, transform)),
        filter((result) => result !== EMPTY),
      )
      .subscribe((response) => client.send(JSON.stringify(response)));
  }

  private bindMessageHandler(
    buffer: { data?: unknown },
    handlers: MessageMappingProperties[],
    transform: (data: unknown) => Observable<unknown>,
  ): Observable<unknown> {
    try {
      const message = JSON.parse(String(buffer.data));
      const handler = handlers.find((h) => h.message === message.event);
      return handler ? transform(handler.callback(message.data)) : EMPTY;
    } catch {
      return EMPTY;
    }
  }
}
