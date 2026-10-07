import { NextResponse, type NextRequest } from "next/server";
import { launchAt } from "./app/launch";

const API = process.env.API_INTERNAL_URL || "http://127.0.0.1:8000";

// Before launch only signed-in admins see the site. Every other page request gets the
// countdown (/soon), which loads none of the site's code or styles, so the topic cannot
// be read from the page source either.
export async function proxy(request: NextRequest) {
  if (Date.now() >= launchAt() || (await isAdmin(request))) return;
  return NextResponse.rewrite(new URL("/soon", request.url));
}

// The API checks the session, so a forged or expired cookie never passes. If the API
// cannot answer, the site stays hidden.
async function isAdmin(request: NextRequest) {
  const session = request.cookies.get("admin_session")?.value;
  if (!session) return false;
  try {
    const response = await fetch(`${API}/api/auth/me`, {
      headers: { cookie: `admin_session=${session}` },
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    return response.ok && (await response.json()).role === "ADMIN";
  } catch {
    return false;
  }
}

// Pages only: not the API, build output or files in public/.
export const config = { matcher: "/((?!api/|_next/|.*\\..*).*)" };
