"""Harvester 공통 인터페이스 — 마스터 플랜 §5.1.

각 source(GEO/SRA/ENA/HCA/GDC...)는 본 ABC 를 구현한다.
주의:
    - source 의 raw payload 는 그대로 datasets.raw_metadata 에 보존되어야 한다 — LLM 추출 버전
      변경 시 재추출이 가능해야 한다.
    - rate limit 은 코드에 박지 말고 환경변수 또는 settings 로 분리 (마스터 플랜 §5.1).
    - L0(Public) 데이터만 다루므로 §12 보안 control(envelope encryption 등)은 적용되지 않는다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime


class Harvester(ABC):
    """ABC for all source-specific harvesters."""

    source_db: str  # 'GEO' | 'SRA' | 'ENA' | 'HCA' | 'GDC' | ...

    @abstractmethod
    async def list_updated_since(self, since: datetime) -> AsyncIterator[str]:
        """Yield source-native record ids updated since `since`.

        구현체는 incremental 호출을 위해 내부적으로 cursor/page 를 관리한다.
        반드시 idempotent 해야 한다 — 같은 since 입력에 같은 결과 집합.
        """

    @abstractmethod
    async def fetch_raw(self, source_id: str) -> dict:
        """Fetch raw metadata.

        반환 dict 는 source 의 원본 payload 를 그대로 보존해야 한다 — 가공 금지.
        datasets.raw_metadata JSONB 컬럼에 그대로 저장된다.
        """
