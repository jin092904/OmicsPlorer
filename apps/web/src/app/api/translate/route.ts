// Server-side proxy for POST /api/v1/datasets/{id}/translate?lang=ko.
// 클라이언트 컴포넌트가 process.env.API_BASE_URL 을 못 보므로 본 handler 가 forward.

import { NextRequest, NextResponse } from "next/server";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const id = req.nextUrl.searchParams.get("id");
  const lang = req.nextUrl.searchParams.get("lang") ?? "ko";
  if (!id || !/^[0-9a-f-]{36}$/i.test(id)) {
    return NextResponse.json({ error: "invalid id" }, { status: 400 });
  }
  const resp = await fetch(
    `${API_BASE_URL}/api/v1/datasets/${id}/translate?lang=${encodeURIComponent(lang)}`,
    { method: "POST", cache: "no-store" },
  );
  const body = await resp.text();
  return new NextResponse(body, {
    status: resp.status,
    headers: { "content-type": resp.headers.get("content-type") ?? "application/json" },
  });
}
