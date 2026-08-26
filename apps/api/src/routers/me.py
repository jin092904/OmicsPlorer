"""`/me/*` — 인증 필수 사용자 라우터.

ADR 0005:
- 모든 엔드포인트가 `Depends(require_user)` → 401 강제.
- 첫 호출 시 `ensure_user_for_principal` 이 tenant + user 를 lazy create.
- 이후 모든 DB 액세스는 `with_tenant_scope(tenant_id)` 안에서 — RLS 가 cross-tenant 차단.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.schemas.me import (
    MePrincipal,
    SaveDatasetRequest,
    SaveDatasetResponse,
    SavedDatasetList,
    SavedDatasetSummary,
    UpdateProfileRequest,
)
from src.security.firebase_auth import FirebasePrincipal, require_user
from src.services.saved_datasets import add_saved, list_saved_for_user, remove_saved
from src.services.users import ensure_user_for_principal, update_nickname

router = APIRouter(prefix="/me", tags=["me"])


def _to_me(principal: FirebasePrincipal, ctx) -> MePrincipal:
    return MePrincipal(
        uid=principal.uid,
        email=principal.email,
        email_verified=principal.email_verified,
        name=principal.name,
        picture=principal.picture,
        nickname=ctx.nickname,
        user_id=str(ctx.user_id),
        tenant_id=str(ctx.tenant_id),
    )


@router.get("", response_model=MePrincipal)
async def get_me(
    principal: FirebasePrincipal = Depends(require_user),
) -> MePrincipal:
    ctx = await ensure_user_for_principal(principal)
    return _to_me(principal, ctx)


@router.patch("/profile", response_model=MePrincipal)
async def patch_profile(
    body: UpdateProfileRequest,
    principal: FirebasePrincipal = Depends(require_user),
) -> MePrincipal:
    try:
        ctx = await update_nickname(principal=principal, nickname=body.nickname)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from None
    return _to_me(principal, ctx)


@router.get("/saved", response_model=SavedDatasetList)
async def get_saved(
    principal: FirebasePrincipal = Depends(require_user),
) -> SavedDatasetList:
    ctx = await ensure_user_for_principal(principal)
    rows = await list_saved_for_user(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
    return SavedDatasetList(
        items=[SavedDatasetSummary(**r) for r in rows],
    )


@router.post("/saved", response_model=SaveDatasetResponse)
async def post_saved(
    body: SaveDatasetRequest,
    principal: FirebasePrincipal = Depends(require_user),
) -> SaveDatasetResponse:
    ctx = await ensure_user_for_principal(principal)
    try:
        dataset_uuid = UUID(body.dataset_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid dataset_id"
        ) from None
    saved = await add_saved(
        tenant_id=ctx.tenant_id, user_id=ctx.user_id, dataset_id=dataset_uuid
    )
    return SaveDatasetResponse(saved=saved)


@router.delete("/saved/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved(
    dataset_id: UUID,
    principal: FirebasePrincipal = Depends(require_user),
) -> None:
    ctx = await ensure_user_for_principal(principal)
    await remove_saved(
        tenant_id=ctx.tenant_id, user_id=ctx.user_id, dataset_id=dataset_id
    )
