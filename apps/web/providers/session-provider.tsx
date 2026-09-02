"use client";
import { createContext, useContext } from "react";
import type { FrontendSession } from "../lib/auth/types";
const SessionContext = createContext<FrontendSession | null>(null);
export function SessionProvider({ session, children }: { session: FrontendSession; children: React.ReactNode }) {
  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
}
export function useFrontendSession(): FrontendSession {
  const session = useContext(SessionContext);
  if (!session) throw new Error("Authenticated frontend session is unavailable");
  return session;
}
