import { type NextRequest, NextResponse } from "next/server";

import { CONSOLE_CLIENT_ID, consoleConfig } from "@/lib/server/config";
import { problem } from "@/lib/server/problem";
import { clearSession, readSession, requestGuard } from "@/lib/server/session";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<Response> {
  const config = consoleConfig();
  const refused = requestGuard(request, config);
  if (refused) return problem(403, "forbidden", refused);

  const session = await readSession(request, config);
  if (session) {
    // Revoking the refresh token kills its family and the access tokens issued from it.
    const tokens = [session.refreshToken, session.accessToken].filter((t): t is string => Boolean(t));
    await Promise.allSettled(
      tokens.map((token) =>
        fetch(`${config.apiOrigin}/oauth/revoke`, {
          method: "POST",
          headers: { "content-type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({ token, client_id: CONSOLE_CLIENT_ID }),
          signal: AbortSignal.timeout(5_000),
        }),
      ),
    );
  }
  // The browser still holds the authorization server's sign-in cookie; send it there to end that too.
  const next = new URL("/oauth/logout", config.issuer);
  next.search = new URLSearchParams({
    client_id: CONSOLE_CLIENT_ID,
    post_logout_redirect_uri: new URL("/signed-out", config.consoleUrl).toString(),
  }).toString();
  const response = NextResponse.json({ next: next.toString() }, { headers: { "cache-control": "no-store" } });
  clearSession(response);
  return response;
}
