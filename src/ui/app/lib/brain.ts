import { NextResponse } from "next/server";
const base = process.env.BRAIN_SERVICE_URL ?? "http://127.0.0.1:8000";
export async function proxy(path: string, request?: Request) {
  try {
    const method = request?.method ?? "GET";
    const response = await fetch(`${base}${path}`, {
      method,
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: method === "GET" ? undefined : await request?.text(),
      signal: AbortSignal.timeout(10000),
    });
    return new NextResponse(await response.text(), {
      status: response.status,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return NextResponse.json(
      {
        error: "Evidence service unavailable. Last received data is retained.",
      },
      { status: 503 },
    );
  }
}
