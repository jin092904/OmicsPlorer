// Server-side proxy for POST /api/v1/ai-pick.
//
// 클라이언트 컴포넌트 (AiPickCard) 는 process.env.API_BASE_URL 을 못 보므로
// 본 route handler 가 API_BASE_URL 환경변수를 갖고 backend 로 forward 한다.
// ?nocache=1 (다시 추천 버튼) 과 JSON body 를 그대로 통과시킨다.

import { NextRequest, NextResponse } from "next/server";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const nocache = req.nextUrl.searchParams.get("nocache");
  const body = await req.text();
  const url = `${API_BASE_URL}/api/v1/ai-pick${
    nocache ? `?nocache=${encodeURIComponent(nocache)}` : ""
  }`;
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    cache: "no-store",
  });
  const out = await resp.text();
  return new NextResponse(out, {
    status: resp.status,
    headers: { "content-type": resp.headers.get("content-type") ?? "application/json" },
  });
}
