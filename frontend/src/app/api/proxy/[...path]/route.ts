/**
 * Next.js catch-all proxy route: /api/proxy/** → backend/**
 *
 * Why this exists:
 *   The browser only ever talks to the Next.js origin (one public URL, works
 *   behind an ngrok/cloudflared tunnel). This handler forwards to the backend
 *   server-side, so visitors never need to reach the backend port directly.
 *
 * Security:
 *   X-User-Id is derived ONLY from the cryptographically-verified NextAuth JWT
 *   here — any X-User-Id the browser tries to send is discarded (we build a
 *   fresh header object). This is what prevents a logged-in user from spoofing
 *   another user's / an admin's id. It MUST stay a code handler: a plain
 *   next.config rewrite would pass the client's headers straight through.
 */

import { NextRequest, NextResponse } from "next/server";
import { getToken } from "next-auth/jwt";

// Server-side backend URL (container-to-container). NEXT_PUBLIC_API_URL is
// "/api/proxy" in this deployment, so it must NOT be used here.
const BACKEND =
  process.env.INTERNAL_API_URL ??
  process.env.BACKEND_URL ??
  "http://localhost:8000";

// Response headers worth forwarding from the backend (e.g. CSV/JSON downloads).
const PASSTHROUGH_RESPONSE_HEADERS = ["content-type", "content-disposition"];

async function forward(
  request: NextRequest,
  params: { path: string[] },
): Promise<NextResponse> {
  const path      = params.path.join("/");
  const search    = new URL(request.url).search;
  const targetUrl = `${BACKEND}/${path}${search}`;

  const token = await getToken({ req: request, secret: process.env.NEXTAUTH_SECRET });
  const forwardHeaders: Record<string, string> = {
    "Content-Type": "application/json",
  };
  // Prefer the DB user id (token.userId, set in the jwt callback) over token.sub,
  // which for OAuth users is the provider's account id, not our user id.
  const userId = (token as { userId?: string } | null)?.userId ?? token?.sub;
  if (userId)       forwardHeaders["X-User-Id"]    = String(userId);
  if (token?.email) forwardHeaders["X-User-Email"] = token.email;

  // Shared secret proving this request came from the trusted Next.js server and
  // not a direct caller to the backend. The backend enforces it on identity
  // endpoints (see backend/app/internal_auth.py). No-op when unset (dev).
  const internalSecret = process.env.INTERNAL_API_SECRET;
  if (internalSecret) forwardHeaders["X-Internal-Secret"] = internalSecret;

  // Forward the real client IP so backend rate limits are per-user, not per
  // proxy-container. Prefer the inbound X-Forwarded-For (set by the tunnel);
  // fall back to the direct request IP.
  const fwd = request.headers.get("x-forwarded-for") ?? request.headers.get("x-real-ip") ?? "";
  if (fwd) forwardHeaders["X-Forwarded-For"] = fwd;

  try {
    // Forward the body for POST/PUT/PATCH/DELETE; GET and HEAD must not.
    const hasBody = !["GET", "HEAD"].includes(request.method);

    // Analysis + chat endpoints call external APIs (Groq, Odds API) — give
    // them 30 s before we give up and surface a 504 to the browser.
    const isSlowPath = path.includes("analysis") || path.startsWith("chat");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), isSlowPath ? 30_000 : 10_000);

    const res = await fetch(targetUrl, {
      method:  request.method,
      headers: forwardHeaders,
      body:    hasBody ? await request.text() : undefined,
      cache:  "no-store",
      signal: controller.signal,
    }).finally(() => clearTimeout(timer));

    const body = await res.text();
    const responseHeaders: Record<string, string> = {};
    for (const h of PASSTHROUGH_RESPONSE_HEADERS) {
      const v = res.headers.get(h);
      if (v) responseHeaders[h] = v;
    }
    if (!responseHeaders["content-type"]) responseHeaders["content-type"] = "application/json";

    return new NextResponse(body, { status: res.status, headers: responseHeaders });
  } catch (err: unknown) {
    const isTimeout = err instanceof Error && err.name === "AbortError";
    if (isTimeout) {
      console.error(`[proxy] Timeout: ${path}`);
      return NextResponse.json({ error: "Request timed out" }, { status: 504 });
    }
    console.error("[proxy] Backend unreachable:", err);
    return NextResponse.json(
      { error: "Backend service unavailable" },
      { status: 503 },
    );
  }
}

export const GET    = (req: NextRequest, { params }: { params: { path: string[] } }) =>
  forward(req, params);
export const POST   = (req: NextRequest, { params }: { params: { path: string[] } }) =>
  forward(req, params);
export const PATCH  = (req: NextRequest, { params }: { params: { path: string[] } }) =>
  forward(req, params);
export const PUT    = (req: NextRequest, { params }: { params: { path: string[] } }) =>
  forward(req, params);
export const DELETE = (req: NextRequest, { params }: { params: { path: string[] } }) =>
  forward(req, params);
