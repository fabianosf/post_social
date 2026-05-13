import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const session = request.cookies.get("session");
  const path = request.nextUrl.pathname;

  // Authenticated users on the landing page go straight to dashboard
  if (path === "/" && session) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  // Protect dashboard and settings — unauthenticated users redirect to login
  if (path !== "/" && !session) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", path);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/", "/dashboard", "/dashboard/:path*", "/settings/:path*", "/discover", "/discover/:path*"],
};
