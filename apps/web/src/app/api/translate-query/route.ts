// Server-side proxy for POST /api/v1/translate-query.
// 한국어 → 영어 자유 텍스트 검색 쿼리 번역.

import { NextRequest, NextResponse } from "next/server";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  let body: { text?: string; target_lang?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }
  if (!body.text || typeof body.text !== "string") {
    return NextResponse.json({ error: "text required" }, { status: 400 });
  }
  const resp = await fetch(`${API_BASE_URL}/api/v1/translate-query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: body.text, target_lang: body.target_lang ?? "en" }),
    cache: "no-store",
  });
  const respBody = await resp.text();
  return new NextResponse(respBody, {
    status: resp.status,
    headers: { "content-type": resp.headers.get("content-type") ?? "application/json" },
  });
}
