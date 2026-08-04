"""Guild-scoped AI config endpoints, mounted under ``/g/{guild_id}/settings``.

Two surfaces:
- **Guild admin** — CRUD of ``guild_ai_connections`` (used when the global mode
  is ``guild``). A connection's ``base_url`` is validated public-only, so a
  guild admin can never persist a private/internal target.
- **Member** (any authenticated guild member) — attach an own key + pick a
  connection (``/ai/me``). Members never set a destination.

The global mode + operator connections (``platform`` mode) live in
``platform_endpoints/ai_settings.py``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
    require_guild_roles,
)
from app.models.platform.guild import GuildRole
from app.models.platform.user import User
from app.schemas.ai_settings import (
    AIConnectionCreate,
    AIConnectionResponse,
    AIConnectionTestResponse,
    AIConnectionUpdate,
    AIModelsResponse,
    ConnectionScope,
    MemberAIKeyUpdate,
    MemberAIPrefUpdate,
    MemberAIView,
    ResolvedAISettingsResponse,
)
from app.services import ai_settings as ai_settings_service

router = APIRouter()

# Guild connection management: real guild admins OR a ``support`` (scoped PAM)
# grantee. Reads work for any support grant; writes are denied at the Postgres
# role level for a read grant (it assumes ``guild_<id>_ro``), so the read/write
# split is DB-enforced.
GuildAdminContext = Annotated[
    GuildContext, Depends(require_guild_roles(GuildRole.admin, GuildRole.support))
]
GuildMemberContext = Annotated[GuildContext, Depends(get_guild_membership)]
CurrentUser = Annotated[User, Depends(get_current_active_user)]


# --- Guild connections (guild admin — guild config mode) ---------------------
@router.get("/ai/connections", response_model=list[AIConnectionResponse])
async def list_guild_connections(
    session: RLSSessionDep,
    _ctx: GuildAdminContext,
) -> list[AIConnectionResponse]:
    return await ai_settings_service.list_guild_connections(session)


@router.post("/ai/connections", response_model=AIConnectionResponse)
async def create_guild_connection(
    payload: AIConnectionCreate,
    session: RLSSessionDep,
    ctx: GuildAdminContext,
    user: CurrentUser,
) -> AIConnectionResponse:
    return await ai_settings_service.create_guild_connection(
        session, ctx.guild_id, user.id, payload
    )


@router.put("/ai/connections/{connection_id}", response_model=AIConnectionResponse)
async def update_guild_connection(
    connection_id: int,
    payload: AIConnectionUpdate,
    session: RLSSessionDep,
    _ctx: GuildAdminContext,
) -> AIConnectionResponse:
    return await ai_settings_service.update_guild_connection(
        session, connection_id, payload
    )


@router.delete(
    "/ai/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_guild_connection(
    connection_id: int,
    session: RLSSessionDep,
    _ctx: GuildAdminContext,
) -> None:
    await ai_settings_service.delete_guild_connection(session, connection_id)


@router.post(
    "/ai/connections/{connection_id}/test", response_model=AIConnectionTestResponse
)
async def test_guild_connection(
    connection_id: int,
    session: RLSSessionDep,
    _ctx: GuildAdminContext,
) -> AIConnectionTestResponse:
    return await ai_settings_service.test_guild_connection(session, connection_id)


@router.post("/ai/connections/{connection_id}/models", response_model=AIModelsResponse)
async def fetch_guild_connection_models(
    connection_id: int,
    session: RLSSessionDep,
    _ctx: GuildAdminContext,
) -> AIModelsResponse:
    return await ai_settings_service.fetch_guild_connection_models(
        session, connection_id
    )


# --- Member surface (any authenticated guild member) -------------------------
@router.get("/ai/me", response_model=MemberAIView)
async def get_member_ai(
    session: RLSSessionDep,
    ctx: GuildMemberContext,
    user: CurrentUser,
) -> MemberAIView:
    """List the connections available to the member (no keys), whether they've
    attached their own key to each, and which one is selected."""
    return await ai_settings_service.get_member_ai_view(session, user, ctx.guild_id)


@router.put("/ai/me/key", response_model=MemberAIView)
async def set_member_key(
    payload: MemberAIKeyUpdate,
    session: RLSSessionDep,
    ctx: GuildMemberContext,
    user: CurrentUser,
) -> MemberAIView:
    """Attach/replace the member's own key for a connection."""
    return await ai_settings_service.set_member_key(
        session, user, ctx.guild_id, payload
    )


@router.delete("/ai/me/key/{scope}/{connection_id}", response_model=MemberAIView)
async def delete_member_key(
    scope: ConnectionScope,
    connection_id: int,
    session: RLSSessionDep,
    ctx: GuildMemberContext,
    user: CurrentUser,
) -> MemberAIView:
    return await ai_settings_service.delete_member_key(
        session, user, ctx.guild_id, scope, connection_id
    )


@router.put("/ai/me/pref", response_model=MemberAIView)
async def set_member_pref(
    payload: MemberAIPrefUpdate,
    session: RLSSessionDep,
    ctx: GuildMemberContext,
    user: CurrentUser,
) -> MemberAIView:
    """Pick the connection the member uses and whether AI is on for them."""
    return await ai_settings_service.set_member_pref(
        session, user, ctx.guild_id, payload
    )


@router.post("/ai/me/test", response_model=AIConnectionTestResponse)
async def test_member_ai(
    session: RLSSessionDep,
    ctx: GuildMemberContext,
    user: CurrentUser,
) -> AIConnectionTestResponse:
    """Test the member's currently-selected connection with their effective key."""
    return await ai_settings_service.test_member_connection(session, user, ctx.guild_id)


# --- Resolved settings (any authenticated guild member) ----------------------
@router.get("/ai/resolved", response_model=ResolvedAISettingsResponse)
async def get_resolved_ai_settings(
    session: RLSSessionDep,
    ctx: GuildMemberContext,
    user: CurrentUser,
) -> ResolvedAISettingsResponse:
    """Resolved (effective) AI settings for the member, without the API key."""
    return await ai_settings_service.get_resolved_ai_settings_response(
        session, user, ctx.guild_id
    )
