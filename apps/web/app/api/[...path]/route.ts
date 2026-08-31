import { NextRequest, NextResponse } from "next/server";

/**
 * Same-origin proxy: browser -> /api/* (vercel.app) -> Render API.
 *
 * Why this exists: direct browser -> onrender.com connections suffer
 * ECONNRESET on some networks, and Vercel edge rewrites to onrender.com are
 * blocked by SSRF protection. A route handler performs the Render fetch
 * server-side with retries — the browser only ever talks to vercel.app.
 */
const RENDER_API = process.env.RENDER_API_URL ?? "https://thai2d-api.onrender.com";

async function proxy(req: NextRequest): Promise<NextResponse> {
  const url = new URL(req.url);
  const target = `${RENDER_API}/api${url.pathname.replace(/^\/api/, "")}${url.search}`;

  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const res = await fetch(target, {
        method: req.method,
        headers: { Accept: "application/json" },
        body: req.method === "POST" ? await req.text() : undefined,
        signal: AbortSignal.timeout(25000),
        cache: "no-store",
      });
      const text = await res.text();
      return new NextResponse(text, {
        status: res.status,
        headers: { "Content-Type": "application/json" },
      });
    } catch (err) {
      if (attempt === 3) {
        return NextResponse.json({ error: "unreachable" }, { status: 502 });
      }
      await new Promise((r) => setTimeout(r, 600 * attempt));
    }
  }
  return NextResponse.json({ error: "unreachable" }, { status: 502 });
}

export { proxy as GET, proxy as POST };
