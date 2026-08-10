import { type NextRequest, NextResponse } from "next/server";

import { ADMIN_SCOPE, CONSOLE_CLIENT_ID, ConfigError, consoleConfig } from "@/lib/server/config";
import { problem } from "@/lib/server/problem";
import { pkceChallenge, randomToken } from "@/lib/server/seal";
import { safeReturnTo, writePendingLogin } from "@/lib/server/session";

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

  const returnTo = safeReturnTo(request.nextUrl.searchParams.get("returnTo"));
  if (host !== config.consoleUrl.host) {
    // The registered redirect URI names one origin; start from it so the session cookie lands there.
    const canonical = new URL("/api/auth/login", config.consoleUrl);
    canonical.searchParams.set("returnTo", returnTo);
    return NextResponse.redirect(canonical, 303);
  }

  const state = randomToken(24);
  const verifier = randomToken(48);
  const authorize = new URL("/oauth/authorize", config.issuer);
  authorize.search = new URLSearchParams({
    response_type: "code",
    client_id: CONSOLE_CLIENT_ID,
    redirect_uri: config.redirectUri,
    scope: ADMIN_SCOPE,
    resource: config.adminResource,
    code_challenge: await pkceChallenge(verifier),
    code_challenge_method: "S256",
    state,
  }).toString();

  const response = NextResponse.redirect(authorize, 303);
  response.headers.set("cache-control", "no-store");
  await writePendingLogin(response, { state, verifier, returnTo }, config);
  return response;
}
