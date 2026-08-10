import { type NextRequest, NextResponse } from "next/server";

import { ConfigError, consoleConfig } from "@/lib/server/config";
import { problem } from "@/lib/server/problem";
import {
  TokenEndpointError,
  clearPendingLogin,
  exchangeCode,
  readPendingLogin,
  writeSession,
} from "@/lib/server/session";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<Response> {
  let config;
  try {
    config = consoleConfig();
  } catch (error) {
    if (error instanceof ConfigError) return problem(500, "console_not_configured", error.message);
    throw error;
  }
  const host = request.headers.get("host");
  if (!host || !config.allowedHosts.has(host)) return problem(400, "bad_host", "Unexpected Host header");

  const params = request.nextUrl.searchParams;
  const pending = await readPendingLogin(request, config);
  if (!pending || params.get("state") !== pending.state) {
    return problem(400, "invalid_state", "This sign-in link expired or was not started here. Sign in again.");
  }
  // RFC 9207: the issuer must be the one we sent the user to, which defeats authorization server mix-up.
  const iss = params.get("iss");
  if (iss !== null && iss !== config.issuer) return problem(400, "issuer_mismatch", "Unexpected issuer");

  const error = params.get("error");
  if (error) {
    const description = params.get("error_description") ?? error;
    return problem(403, error, description);
  }
  const code = params.get("code");
  if (!code) return problem(400, "invalid_request", "The authorization response had no code");

  try {
    const session = await exchangeCode(config, code, pending.verifier);
    const response = NextResponse.redirect(new URL(pending.returnTo, config.consoleUrl), 303);
    response.headers.set("cache-control", "no-store");
    clearPendingLogin(response);
    await writeSession(response, session, config);
    return response;
  } catch (failure) {
    if (failure instanceof TokenEndpointError) return problem(502, "token_exchange_failed", failure.message);
    return problem(502, "token_exchange_failed", "Could not reach the Toolgate authorization server");
  }
}
