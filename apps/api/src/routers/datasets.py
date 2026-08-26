"""Dataset endpoints — `GET /datasets/{id}` 등."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from src.schemas.dataset import DatasetDetail
from src.services.dataset import fetch_dataset

router = APIRouter()


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail)
async def get_dataset(dataset_id: UUID) -> DatasetDetail:
    row = await fetch_dataset(dataset_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dataset not found")
    return DatasetDetail.model_validate(row)
