"""Guild storage usage for the SPA's usage panel.

A guild admin's settings page shows storage used against the operator-set
cap (``guilds.max_storage_bytes``). The number is the same
``SUM(uploads.size_bytes)`` that ``enforce_storage_quota`` enforces against,
read under the guild-routed RLS session; it renders regardless of whether an
external billing URL is configured. Guild-admin only — the guild-wide total
mirrors the admin-only settings surface it backs (like ``status``, it is not
disclosed to regular members).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.core.messages import GuildMessages
from app.api.deps import (
    RLSSessionDep,
    GuildContextDep,
    CurrentUser,
)
from app.schemas.base import SanitizedBaseModel
from app.services.tenant.attachments import get_guild_storage_usage

router = APIRouter()


class GuildStorageUsageRead(SanitizedBaseModel):
    guild_id: int
    usage_bytes: int


@router.get("/usage", response_model=GuildStorageUsageRead)
async def read_storage_usage(
    current_user: CurrentUser,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
) -> GuildStorageUsageRead:
    if not guild_context.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_ADMIN_REQUIRED,
        )
    usage_bytes = await get_guild_storage_usage(session)
    return GuildStorageUsageRead(
        guild_id=guild_context.guild_id, usage_bytes=usage_bytes
    )
