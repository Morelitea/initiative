"""Apps installed into a guild.

Reading is open to every member — the sidebar has to know which apps are there,
and an app's existence is guild-wide knowledge. Installing, renaming, disabling
and removing are guild-admin actions: an app mounts a guild-wide surface, which
is the guild's shape rather than any one member's.

What a member may *do* inside an app is not decided here. The content an app
creates carries its own grants, and the tool that owns it enforces them exactly
as it does for initiative content.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import GuildAppMessages, MarketplaceMessages
from app.db import session as db_session
from app.models.platform.user import User
from app.models.tenant.guild_app import GuildApp
from app.schemas.tenant.guild_app import (
    GuildAppInstall,
    GuildAppListResponse,
    GuildAppRead,
    GuildAppUpdate,
    serialize_guild_app,
)
from app.services import rls as rls_service
from app.services.marketplace import catalog as catalog_service
from app.services.platform import guilds as guilds_service
from app.services.tenant import guild_apps as guild_apps_service

logger = logging.getLogger(__name__)

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


def _require_guild_admin(guild_context: GuildContext) -> None:
    if not rls_service.is_guild_admin(guild_context.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildAppMessages.ADMIN_REQUIRED,
        )


async def _load(session: RLSSessionDep, app_id: int) -> GuildApp:
    app = (await session.exec(select(GuildApp).where(GuildApp.id == app_id))).first()
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildAppMessages.NOT_FOUND,
        )
    return app


@router.get("/", response_model=GuildAppListResponse)
async def list_guild_apps(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> GuildAppListResponse:
    """Every app installed in this guild, enabled or not.

    Disabled ones are included so an admin can find and re-enable them; the
    sidebar filters to enabled.
    """
    apps = (
        await session.exec(select(GuildApp).order_by(GuildApp.name, GuildApp.id))
    ).all()
    return GuildAppListResponse(items=[serialize_guild_app(app) for app in apps])


@router.post("/", response_model=GuildAppRead, status_code=status.HTTP_201_CREATED)
async def install_guild_app(
    payload: GuildAppInstall,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> GuildAppRead:
    """Install a listing as a guild app.

    The request names a listing; everything stored comes from the catalog row
    and from what the install creates here. One install per listing: an app
    mounts a single guild-wide surface, so a second copy would have nothing to
    be — rename or re-share the one that exists instead.
    """
    _require_guild_admin(guild_context)

    listing = await catalog_service.get_listing_by_uid(session, payload.listing_uid)
    if listing is None or listing.kind != "app":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MarketplaceMessages.LISTING_NOT_FOUND,
        )
    if not listing.available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=MarketplaceMessages.LISTING_UNAVAILABLE,
        )
    version = await catalog_service.resolve_installable_version(session, listing)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=MarketplaceMessages.LISTING_VERSION_INCOMPATIBLE,
        )

    existing = (
        await session.exec(select(GuildApp).where(GuildApp.listing_uid == listing.uid))
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildAppMessages.ALREADY_INSTALLED,
        )

    definition = dict(version.definition)
    if definition.get("app_kind") != "tool_instance":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildAppMessages.NOT_AN_APP,
        )

    name = (payload.name or definition.get("default_name") or listing.name).strip()
    config = await guild_apps_service.create_app_content(
        session,
        definition=definition,
        guild_id=guild_context.guild_id,
        created_by_id=current_user.id,
        name=name,
    )

    app = GuildApp(
        guild_id=guild_context.guild_id,
        listing_uid=listing.uid,
        listing_version=version.version,
        app_kind=definition["app_kind"],
        name=name,
        definition=definition,
        config=config,
        installed_by_id=current_user.id,
    )
    session.add(app)
    await session.commit()
    await session.refresh(app)

    await _count_install(listing.id)
    return serialize_guild_app(app)


@router.patch("/{app_id}", response_model=GuildAppRead)
async def update_guild_app(
    app_id: int,
    payload: GuildAppUpdate,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> GuildAppRead:
    """Rename an app, or turn it off without removing what it created."""
    _require_guild_admin(guild_context)
    app = await _load(session, app_id)

    data = payload.model_dump(exclude_unset=True)
    if data.get("name"):
        app.name = data["name"].strip()
    if "enabled" in data and data["enabled"] is not None:
        app.enabled = data["enabled"]
    app.updated_at = datetime.now(timezone.utc)
    session.add(app)
    await session.commit()
    await session.refresh(app)
    return serialize_guild_app(app)


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
async def uninstall_guild_app(
    app_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """Remove an app, moving what it created to the trash.

    Trashed rather than deleted: the events someone put in a guild calendar
    should survive an admin removing the app, for as long as the guild's
    retention window allows.
    """
    _require_guild_admin(guild_context)
    app = await _load(session, app_id)

    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await guild_apps_service.remove_app_content(
        session,
        app,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.delete(app)
    await session.commit()


async def _count_install(listing_id) -> None:
    """Tally the install against its listing, after the fact and best-effort —
    the catalog has no request-path writer, and a failed tally must not undo an
    install that already happened."""
    if listing_id is None:
        return
    try:
        async with db_session.AdminSessionLocal() as admin:
            await catalog_service.bump_installs_count(admin, listing_id)
            await admin.commit()
    except Exception:
        logger.warning(
            "marketplace: install count bump failed for listing %s",
            listing_id,
            exc_info=True,
        )
