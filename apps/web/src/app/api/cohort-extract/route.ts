// Server-side proxy for POST /api/v1/datasets/{id}/cohort/extract.
//
// 클라이언트 컴포넌트 (ExperimentDesign) 는 process.env.API_BASE_URL 을 못 보므로
// 본 route handler 가 API_BASE_URL 환경변수를 갖고 backend 로 forward 한다.

import { NextRequest, NextResponse } from "next/server";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const id = req.nextUrl.searchParams.get("id");
  if (!id || !/^[0-9a-f-]{36}$/i.test(id)) {
    return NextResponse.json({ error: "invalid id" }, { status: 400 });
  }
  const resp = await fetch(
    `${API_BASE_URL}/api/v1/datasets/${id}/cohort/extract`,
    { method: "POST", cache: "no-store" },
  );
  const body = await resp.text();
  return new NextResponse(body, {
    status: resp.status,
    headers: { "content-type": resp.headers.get("content-type") ?? "application/json" },
  });
}
