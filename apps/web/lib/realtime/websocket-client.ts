"use client";
import { gatewayOriginForRealtime } from "../api/gateway-client";
export function createGatewayWebSocket(path: `/api/v1/${string}`): WebSocket {
  const explicit = process.env.NEXT_PUBLIC_GATEWAY_WS_URL;
  const base = explicit ?? gatewayOriginForRealtime().replace(/^http/, "ws");
  if (/\/internal\/v1/i.test(base) || /:8000\b/.test(base)) throw new Error("WebSocket URL must target the NestJS gateway only");
  return new WebSocket(`${base.replace(/\/$/, "")}${path}`);
}
