"use client";
import type { FrontendSession } from "../auth/types";
import { gatewayRequest } from "../api/gateway-client";
export type SseMessage = { id?: string; event?: string; data: string };
export async function* streamGatewaySse(path: `/api/v1/${string}`, session: FrontendSession, signal?: AbortSignal, lastEventId?: string): AsyncGenerator<SseMessage> {
  const response = await gatewayRequest(path, session, { headers: { accept: "text/event-stream", ...(lastEventId ? { "last-event-id": lastEventId } : {}) }, signal });
  const reader = response.body?.getReader(); if (!reader) return;
  const decoder = new TextDecoder(); let buffer = "";
  try { while (true) { const { value, done } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream: true }); let boundary; while ((boundary = buffer.indexOf("\n\n")) >= 0) { const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2); const message: SseMessage = { data: "" }; for (const line of frame.split(/\r?\n/)) { const idx=line.indexOf(":"); if(idx<0) continue; const key=line.slice(0,idx), val=line.slice(idx+1).trimStart(); if(key==="data") message.data += `${val}\n`; else if(key==="event") message.event=val; else if(key==="id") message.id=val; } message.data=message.data.replace(/\n$/,""); yield message; } } } finally { reader.releaseLock(); }
}
