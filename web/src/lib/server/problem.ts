import { NextResponse } from "next/server";

export function problem(status: number, title: string, detail: string): NextResponse {
  return NextResponse.json(
    { type: `urn:toolgate:error:${title}`, title, status, detail },
    { status, headers: { "content-type": "application/problem+json", "cache-control": "no-store" } },
  );
}
