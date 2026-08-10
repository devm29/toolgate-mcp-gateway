import { type NextRequest, NextResponse } from "next/server";

import { consoleConfig } from "@/lib/server/config";
import { problem } from "@/lib/server/problem";
import { readSession, requestGuard } from "@/lib/server/session";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<Response> {
  const config = consoleConfig();
  const refused = requestGuard(request, config);
  if (refused) return problem(403, "forbidden", refused);
  const session = await readSession(request, config);
  if (!session) return problem(401, "unauthorized", "Not signed in");
  return NextResponse.json({ subject: session.subject }, { headers: { "cache-control": "no-store" } });
}
