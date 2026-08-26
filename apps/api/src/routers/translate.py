"""Translate 엔드포인트 — 데이터셋 title/abstract → 한국어 (on-demand).

POST /datasets/{id}/translate?lang=ko
  → Redis cache 24h. Phi-4 mini 호출 (5-30s 첫 호출, 캐시 hit 시 즉시).

응답:
    {"title": str|null, "abstract": str|null, "lang": "ko"}

실패 시 503.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text

from src.services.cohort import get_db_engine
from src.services.translate import SUPPORTED_LANGS, translate_dataset, translate_query

router = APIRouter()


class TranslationResponse(BaseModel):
    dataset_id: str
    lang: str
    title: str | None
    abstract: str | None


class QueryTranslationRequest(BaseModel):
    text: str
    target_lang: str = "en"


class QueryTranslationResponse(BaseModel):
    original: str
    translated: str
    target_lang: str


@router.post("/translate-query", response_model=QueryTranslationResponse)
async def post_translate_query(req: QueryTranslationRequest) -> QueryTranslationResponse:
    """검색 쿼리 (자유 텍스트) → 다른 언어. v1: ko → en 만 지원.

    landing page 의 사용자 보조 위젯용 — 한국어로 입력 후 영어로 검색하고 싶을 때.
    """
    if req.target_lang != "en":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="v1 supports target_lang='en' only",
        )
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="text required"
        )
    if len(text) > 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="text too long (>500 chars)",
        )
    translated = await translate_query(text, target_lang=req.target_lang)
    if translated is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="translation failed — try again",
        )
    return QueryTranslationResponse(
        original=text, translated=translated, target_lang=req.target_lang
    )


@router.post(
    "/datasets/{dataset_id}/translate", response_model=TranslationResponse
)
async def post_translate(
    dataset_id: UUID,
    lang: str = Query("ko", description=f"target lang ({'/'.join(sorted(SUPPORTED_LANGS))})"),
) -> TranslationResponse:
    if lang not in SUPPORTED_LANGS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported lang. supported: {sorted(SUPPORTED_LANGS)}",
        )

    eng = get_db_engine()
    async with eng.connect() as conn:
        result = await conn.execute(
            text("SELECT id, title, abstract FROM datasets WHERE id = :id LIMIT 1"),
            {"id": dataset_id},
        )
        row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dataset not found")

    translated = await translate_dataset(
        str(dataset_id),
        title=row["title"],
        abstract=row["abstract"],
        lang=lang,
    )
    if translated is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="translation failed — try again later",
        )
    return TranslationResponse(
        dataset_id=str(dataset_id),
        lang=lang,
        title=translated.get("title"),
        abstract=translated.get("abstract"),
    )
