import type { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

import { ADMIN_SCOPE, CONSOLE_CLIENT_ID, consoleConfig, type ConsoleConfig } from "@/lib/server/config";
import { seal, unseal } from "@/lib/server/seal";

export const SESSION_COOKIE = "toolgate_console";
export const LOGIN_COOKIE = "toolgate_console_login";
const SESSION_MAX_AGE = 60 * 60 * 8;
const REFRESH_SKEW_SECONDS = 30;

const sessionSchema = z.object({
  accessToken: z.string().min(1),
  refreshToken: z.string().min(1).nullable(),
  expiresAt: z.number(),
  subject: z.string(),
});
export type ConsoleSession = z.infer<typeof sessionSchema>;

const loginSchema = z.object({
  state: z.string().min(16),
  verifier: z.string().min(43),
  returnTo: z.string(),
});
export type PendingLogin = z.infer<typeof loginSchema>;

const tokenResponseSchema = z.object({
  access_token: z.string().min(1),
  token_type: z.literal("Bearer"),
  expires_in: z.number().int().positive(),
  scope: z.string(),
  refresh_token: z.string().optional(),
});

export class TokenEndpointError extends Error {}

function subjectOf(accessToken: string): string {
  const payload = accessToken.split(".")[1];
  if (!payload) return "unknown";
  try {
    const claims = z
      .object({ sub: z.string() })
      .safeParse(JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/"))));
    return claims.success ? claims.data.sub : "unknown";
  } catch {
    return "unknown";
  }
}

async function tokenRequest(config: ConsoleConfig, form: Record<string, string>): Promise<ConsoleSession> {
  const response = await fetch(`${config.apiOrigin}/oauth/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded", accept: "application/json" },
    body: new URLSearchParams({ client_id: CONSOLE_CLIENT_ID, ...form }),
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = z.object({ error_description: z.string() }).safeParse(body);
    throw new TokenEndpointError(error.success ? error.data.error_description : `token endpoint ${response.status}`);
  }
  const parsed = tokenResponseSchema.parse(body);
  if (!parsed.scope.split(" ").includes(ADMIN_SCOPE)) {
    throw new TokenEndpointError("The authorization server did not grant the admin scope");
  }
  return {
    accessToken: parsed.access_token,
    refreshToken: parsed.refresh_token ?? null,
    expiresAt: Math.floor(Date.now() / 1000) + parsed.expires_in,
    subject: subjectOf(parsed.access_token),
  };
}

export function exchangeCode(config: ConsoleConfig, code: string, verifier: string): Promise<ConsoleSession> {
  return tokenRequest(config, {
    grant_type: "authorization_code",
    code,
    code_verifier: verifier,
    redirect_uri: config.redirectUri,
    resource: config.adminResource,
  });
}

// Refresh tokens rotate and a reused one revokes the whole family, so parallel requests that all see an
// expired access token must share one refresh. Results are kept briefly for requests still carrying the old cookie.
const refreshes = new Map<string, { promise: Promise<ConsoleSession | null>; at: number }>();
const REFRESH_REUSE_MS = 60_000;

export function refreshSession(config: ConsoleConfig, session: ConsoleSession): Promise<ConsoleSession | null> {
  const refreshToken = session.refreshToken;
  if (!refreshToken) return Promise.resolve(null);
  const now = Date.now();
  for (const [token, entry] of refreshes) {
    if (now - entry.at > REFRESH_REUSE_MS) refreshes.delete(token);
  }
  const existing = refreshes.get(refreshToken);
  if (existing) return existing.promise;
  const promise = tokenRequest(config, { grant_type: "refresh_token", refresh_token: refreshToken }).catch(
    () => null,
  );
  refreshes.set(refreshToken, { promise, at: now });
  return promise;
}

export function needsRefresh(session: ConsoleSession): boolean {
  return session.expiresAt - REFRESH_SKEW_SECONDS <= Math.floor(Date.now() / 1000);
}

export async function readSession(request: NextRequest, config = consoleConfig()): Promise<ConsoleSession | null> {
  const parsed = sessionSchema.safeParse(await unseal(request.cookies.get(SESSION_COOKIE)?.value, config.sessionSecret));
  return parsed.success ? parsed.data : null;
}

export async function writeSession(response: NextResponse, session: ConsoleSession, config = consoleConfig()) {
  response.cookies.set(SESSION_COOKIE, await seal(session, config.sessionSecret), {
    httpOnly: true,
    secure: config.secureCookies,
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_MAX_AGE,
  });
}

export function clearSession(response: NextResponse) {
  response.cookies.set(SESSION_COOKIE, "", { path: "/", maxAge: 0 });
}

export async function readPendingLogin(request: NextRequest, config = consoleConfig()): Promise<PendingLogin | null> {
  const parsed = loginSchema.safeParse(await unseal(request.cookies.get(LOGIN_COOKIE)?.value, config.sessionSecret));
  return parsed.success ? parsed.data : null;
}

export async function writePendingLogin(response: NextResponse, login: PendingLogin, config = consoleConfig()) {
  response.cookies.set(LOGIN_COOKIE, await seal(login, config.sessionSecret), {
    httpOnly: true,
    secure: config.secureCookies,
    sameSite: "lax",
    path: "/api/auth",
    maxAge: 600,
  });
}

export function clearPendingLogin(response: NextResponse) {
  response.cookies.set(LOGIN_COOKIE, "", { path: "/api/auth", maxAge: 0 });
}

/** Only relative, same-app paths may be used as a post-login destination. */
export function safeReturnTo(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return "/";
  return value.startsWith("/api/") ? "/" : value;
}

/**
 * Rejects requests that did not come from the console itself. The Host check defeats DNS rebinding (the
 * attacker's hostname resolves here but cannot be in the allow-list); the Origin and Fetch-Metadata checks stop
 * other sites from driving the proxy with the admin's cookie.
 */
export function requestGuard(request: NextRequest, config = consoleConfig()): string | null {
  const host = request.headers.get("host");
  if (!host || !config.allowedHosts.has(host)) return "Unexpected Host header";
  const site = request.headers.get("sec-fetch-site");
  if (site && site !== "same-origin" && site !== "none") return "Cross-site request refused";
  const method = request.method.toUpperCase();
  if (method !== "GET" && method !== "HEAD") {
    const origin = request.headers.get("origin");
    if (!origin) return "Origin header required";
    try {
      if (!config.allowedHosts.has(new URL(origin).host)) return "Cross-origin request refused";
    } catch {
      return "Malformed Origin header";
    }
  }
  return null;
}
