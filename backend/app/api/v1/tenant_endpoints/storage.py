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

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.models.platform.user import User
from app.schemas.base import SanitizedBaseModel
from app.services.rls import require_guild_admin
from app.services.tenant.attachments import get_guild_storage_usage

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


class GuildStorageUsageRead(SanitizedBaseModel):
    guild_id: int
    usage_bytes: int


@router.get("/usage", response_model=GuildStorageUsageRead)
async def read_storage_usage(
    current_user: CurrentUser,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
) -> GuildStorageUsageRead:
    require_guild_admin(guild_context.role)
    usage_bytes = await get_guild_storage_usage(session)
    return GuildStorageUsageRead(
        guild_id=guild_context.guild_id, usage_bytes=usage_bytes
    )
