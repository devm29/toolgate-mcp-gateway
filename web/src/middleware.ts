import { type NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "toolgate_console";

/** Pages need a console session; the API relay checks the session itself and answers 401 instead. */
export function middleware(request: NextRequest) {
  if (request.cookies.get(SESSION_COOKIE)?.value) return NextResponse.next();
  const login = new URL("/api/auth/login", request.url);
  login.searchParams.set("returnTo", `${request.nextUrl.pathname}${request.nextUrl.search}`);
  return NextResponse.redirect(login, 303);
}

export const config = {
  matcher: ["/((?!api/|_next/|signed-out|favicon.ico|robots.txt).*)"],
};
