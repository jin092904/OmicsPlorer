"""Ontology endpoints — `GET /ontology/labels`."""
from __future__ import annotations

from fastapi import APIRouter, Query

from src.services.ontology import lookup_labels

router = APIRouter()


@router.get("/ontology/labels")
async def get_labels(ids: list[str] = Query(default=[])) -> dict[str, str]:
    """`?ids=MONDO:0005061&ids=CL:0000057` → {curie: label}.

    매칭 실패한 curie 는 응답에서 제외.
    """
    if not ids:
        return {}
    return await lookup_labels(ids)
