import "server-only";
import { cookies } from "next/headers";
import { createHmac, timingSafeEqual } from "node:crypto";
import { redirect } from "next/navigation";
import { z } from "zod";

const SessionSchema = z.object({
  userId: z.string().uuid(),
  tenantId: z.string().uuid(),
  roles: z.array(z.string().min(1)).min(1),
  displayName: z.string().min(1).max(120),
  expiresAt: z.number().int().positive(),
});
export type FrontendSession = z.infer<typeof SessionSchema>;

function decodeBase64Url(value: string): string {
  return Buffer.from(value, "base64url").toString("utf8");
}

function verifySignature(payload: string, signature: string, secret: string): boolean {
  const expected = createHmac("sha256", secret).update(payload).digest("base64url");
  const actual = Buffer.from(signature);
  const expectedBuffer = Buffer.from(expected);
  return actual.length === expectedBuffer.length && timingSafeEqual(actual, expectedBuffer);
}

export function parseSignedSession(raw: string, secret: string, nowMs = Date.now()): FrontendSession | null {
  const [payload, signature] = raw.split(".");
  if (!payload || !signature || !secret || !verifySignature(payload, signature, secret)) return null;
  try {
    const parsed = SessionSchema.parse(JSON.parse(decodeBase64Url(payload)));
    return parsed.expiresAt > nowMs ? parsed : null;
  } catch {
    return null;
  }
}

export function issueSignedSession(session: FrontendSession, secret: string): string {
  const parsed=SessionSchema.parse(session); const payload=Buffer.from(JSON.stringify(parsed),"utf8").toString("base64url");
  const signature=createHmac("sha256",secret).update(payload).digest("base64url"); return `${payload}.${signature}`;
}

export async function getFrontendSession(): Promise<FrontendSession | null> {
  const store = await cookies();
  const raw = store.get("verideploy_session")?.value;
  const secret = process.env.FRONTEND_SESSION_SECRET ?? "";
  if (raw && secret) return parseSignedSession(raw, secret);

  const bypass = process.env.FRONTEND_DEV_AUTH_BYPASS === "true";
  if (bypass && process.env.NODE_ENV !== "production") {
    return {
      userId: process.env.FRONTEND_DEV_USER_ID ?? "22222222-2222-4222-8222-222222222222",
      tenantId: process.env.FRONTEND_DEV_TENANT_ID ?? "11111111-1111-4111-8111-111111111111",
      roles: ["developer"],
      displayName: "Development Operator",
      expiresAt: Date.now() + 60_000,
    };
  }
  return null;
}

export async function requireFrontendSession(): Promise<FrontendSession> {
  const session = await getFrontendSession();
  if (!session) redirect("/sign-in");
  return session;
}
