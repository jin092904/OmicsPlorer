"""`/me` 응답 스키마."""
from __future__ import annotations

from pydantic import BaseModel


class MePrincipal(BaseModel):
    """현재 로그인한 사용자의 토큰 + DB 매핑 요약."""

    uid: str
    email: str | None
    email_verified: bool
    name: str | None
    picture: str | None
    nickname: str | None  # 커뮤니티 노출 별명 (없으면 name/email fallback)
    user_id: str
    tenant_id: str


class UpdateProfileRequest(BaseModel):
    nickname: str | None = None  # null 또는 빈 문자열 → 해제


class SavedDatasetSummary(BaseModel):
    dataset_id: str
    source_db: str
    source_id: str
    title: str
    modality: list[str]
    organism_taxid: list[int]
    saved_at: str | None


class SavedDatasetList(BaseModel):
    items: list[SavedDatasetSummary]


class SaveDatasetRequest(BaseModel):
    dataset_id: str  # UUID — 라우터에서 검증.


class SaveDatasetResponse(BaseModel):
    saved: bool  # 새로 추가했으면 True, 이미 있으면 False.
