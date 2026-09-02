"use client";
import type { FrontendSession } from "../lib/auth/types";
import { QueryProvider } from "./query-provider";
import { SessionProvider } from "./session-provider";
export function AppProviders({ session, children }: { session: FrontendSession; children: React.ReactNode }) {
  return <SessionProvider session={session}><QueryProvider>{children}</QueryProvider></SessionProvider>;
}
