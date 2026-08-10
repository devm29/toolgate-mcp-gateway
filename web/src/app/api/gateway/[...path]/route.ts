import { type NextRequest, NextResponse } from "next/server";

import { ConfigError, consoleConfig } from "@/lib/server/config";
import { problem } from "@/lib/server/problem";
import { needsRefresh, readSession, refreshSession, requestGuard, writeSession } from "@/lib/server/session";

export const dynamic = "force-dynamic";

const REQUEST_TIMEOUT_MS = 20_000;
const PATH_SEGMENT = /^[A-Za-z0-9._~-]+$/;

/**
 * Backend-for-frontend relay to the admin API. The browser only holds a sealed, httpOnly session; this route
 * attaches the signed-in admin's own short-lived JWT, so every action is attributed to that person.
 */
async function proxy(request: NextRequest, path: string[]): Promise<Response> {
  let config;
  try {
    config = consoleConfig();
  } catch (error) {
    if (error instanceof ConfigError) return problem(500, "console_not_configured", error.message);
    throw error;
  }
  const refused = requestGuard(request, config);
  if (refused) return problem(403, "forbidden", refused);
  if (!path.every((segment) => PATH_SEGMENT.test(segment))) {
    return problem(400, "bad_path", "Invalid API path");
  }

  let session = await readSession(request, config);
  if (!session) return problem(401, "unauthorized", "Sign in to the console");
  let refreshed = false;
  if (needsRefresh(session)) {
    const next = await refreshSession(config, session);
    if (!next) return problem(401, "session_expired", "Your session expired. Sign in again.");
    session = next;
    refreshed = true;
  }

  const headers = new Headers({ authorization: `Bearer ${session.accessToken}` });
  for (const name of ["content-type", "accept", "last-event-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const method = request.method;
  const body = method === "GET" || method === "HEAD" ? undefined : await request.text();
  const streaming = request.headers.get("accept")?.includes("text/event-stream") ?? false;
  const signal = streaming
    ? request.signal
    : AbortSignal.any([request.signal, AbortSignal.timeout(REQUEST_TIMEOUT_MS)]);

  let upstream: Response;
  try {
    upstream = await fetch(`${config.apiOrigin}/api/${path.join("/")}${request.nextUrl.search}`, {
      method,
      headers,
      ...(body ? { body } : {}),
      signal,
      cache: "no-store",
    });
  } catch (error) {
    const timedOut = error instanceof DOMException && error.name === "TimeoutError";
    return problem(
      timedOut ? 504 : 502,
      timedOut ? "gateway_timeout" : "bad_gateway",
      timedOut ? "The Toolgate API did not answer in time" : "The Toolgate API is unreachable",
    );
  }

  let response: NextResponse;
  if (upstream.headers.get("content-type")?.includes("text/event-stream")) {
    response = new NextResponse(upstream.body, {
      status: upstream.status,
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache, no-transform",
        connection: "keep-alive",
      },
    });
  } else {
    response = new NextResponse(await upstream.text(), { status: upstream.status });
    const upstreamType = upstream.headers.get("content-type");
    if (upstreamType) response.headers.set("content-type", upstreamType);
    response.headers.set("cache-control", "no-store");
  }
  if (refreshed) await writeSession(response, session, config);
  return response;
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, ctx: Ctx): Promise<Response> {
  return proxy(request, (await ctx.params).path);
}
export async function POST(request: NextRequest, ctx: Ctx): Promise<Response> {
  return proxy(request, (await ctx.params).path);
}
export async function PATCH(request: NextRequest, ctx: Ctx): Promise<Response> {
  return proxy(request, (await ctx.params).path);
}
export async function PUT(request: NextRequest, ctx: Ctx): Promise<Response> {
  return proxy(request, (await ctx.params).path);
}
export async function DELETE(request: NextRequest, ctx: Ctx): Promise<Response> {
  return proxy(request, (await ctx.params).path);
}
