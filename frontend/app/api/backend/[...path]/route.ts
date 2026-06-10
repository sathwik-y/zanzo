import { NextRequest, NextResponse } from "next/server";

// Server-side proxy: the browser never sees the backend API key.
const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";
const API_KEY = process.env.BACKEND_API_KEY ?? "change-me";

async function proxy(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  const search = new URL(req.url).search;
  const target = `${BACKEND}/${path.join("/")}${search}`;

  const headers: Record<string, string> = { "X-API-Key": API_KEY };
  const contentType = req.headers.get("content-type");
  if (contentType) headers["Content-Type"] = contentType;

  const resp = await fetch(target, {
    method: req.method,
    headers,
    body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.text(),
    cache: "no-store",
  });

  const respHeaders: Record<string, string> = {
    "content-type": resp.headers.get("content-type") ?? "application/json",
  };
  const disposition = resp.headers.get("content-disposition");
  if (disposition) respHeaders["content-disposition"] = disposition;

  return new NextResponse(resp.status === 204 ? null : await resp.arrayBuffer(), {
    status: resp.status,
    headers: respHeaders,
  });
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE };
