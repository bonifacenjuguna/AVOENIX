// Backend-for-frontend proxy: same-origin calls from the browser are forwarded to the AVOENIX API with cookies preserved.
// Only the /v1 surface is reachable; the API base URL stays server-side.
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
const BASE = process.env.AVOENIX_API_URL;
const FORWARD_REQ = ["content-type", "cookie", "user-agent", "x-forwarded-for"];

async function proxy(req: NextRequest, { params }: { params: { path: string[] } }) {
  if (!BASE) return NextResponse.json({ error: { code: "not_configured", message: "AVOENIX_API_URL is not set on the Studio server." } }, { status: 503 });
  const path = params.path.join("/");
  if (!/^v1\/[A-Za-z0-9/_.:-]*$/.test(path) || path.includes("..")) return NextResponse.json({ error: { code: "not_found", message: "Unknown route." } }, { status: 404 });
  const headers = new Headers();
  FORWARD_REQ.forEach((h) => { const v = req.headers.get(h); if (v) headers.set(h, v); });
  const ip = req.headers.get("x-forwarded-for"); if (ip) headers.set("x-forwarded-for", ip);
  const init: RequestInit = { method: req.method, headers, cache: "no-store", redirect: "manual", signal: AbortSignal.timeout(25_000) };
  if (!["GET", "HEAD"].includes(req.method)) init.body = await req.text();
  try {
    const upstream = await fetch(`${BASE.replace(/\/$/, "")}/${path}${req.nextUrl.search}`, init);
    const out = new NextResponse(upstream.body, { status: upstream.status });
    out.headers.set("content-type", upstream.headers.get("content-type") ?? "application/json");
    out.headers.set("cache-control", "no-store");
    for (const h of ["content-disposition", "x-message-count"]) { const v = upstream.headers.get(h); if (v) out.headers.set(h, v); }      // conversation export
    out.headers.set("x-content-type-options", "nosniff");
    const cookies = (upstream.headers as any).getSetCookie?.() as string[] | undefined;
    (cookies ?? []).forEach((c) => out.headers.append("set-cookie", c));
    return out;
  } catch {
    return NextResponse.json({ error: { code: "upstream_unreachable", message: "The AVOENIX API did not respond." } }, { status: 502 });
  }
}
export { proxy as GET, proxy as POST, proxy as DELETE };
