"use client";
import type { ZodType } from "zod";
import type { FrontendSession } from "../auth/types";
import { tracedFetch } from "../observability/browser-telemetry";
const fetch = tracedFetch;

export class GatewayApiError extends Error {
  constructor(public readonly status: number, public readonly code: string, message: string, public readonly correlationId?: string) { super(message); }
}

function gatewayOrigin(): string {
  const value = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:4000";
  if (/\/internal\/v1/i.test(value) || /:8000\b/.test(value)) throw new Error("NEXT_PUBLIC_GATEWAY_URL must target the NestJS public gateway only");
  return value.replace(/\/$/, "");
}

export async function gatewayRequest(path: `/api/v1/${string}`, session: FrontendSession, options: RequestInit = {}): Promise<Response> {
  const correlationId = crypto.randomUUID();
  const headers = new Headers(options.headers);
  headers.set("x-tenant-id", session.tenantId);
  headers.set("x-user-id", session.userId);
  headers.set("x-correlation-id", correlationId);
  const response = await fetch(`${gatewayOrigin()}${path}`, { ...options, headers, cache: options.cache ?? "no-store" });
  if (!response.ok) {
    const body = await response.clone().json().catch(() => null);
    const envelope = body?.error;
    throw new GatewayApiError(response.status, envelope?.code ?? "GATEWAY_REQUEST_FAILED", envelope?.message ?? `Gateway request failed with ${response.status}`, envelope?.correlation_id ?? correlationId);
  }
  return response;
}

export async function gatewayFetch<T>(path: `/api/v1/${string}`, session: FrontendSession, options: RequestInit = {}, schema?: ZodType<T>): Promise<T> {
  const response = await gatewayRequest(path, session, options);
  const body = response.status === 204 ? null : await response.json();
  return schema ? schema.parse(body) : body as T;
}

export function gatewayOriginForRealtime(): string { return gatewayOrigin(); }
