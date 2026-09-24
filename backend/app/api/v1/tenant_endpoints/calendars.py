"""Calendar endpoints — the shareable container for events.

A calendar is to events what a project is to tasks: creation is gated at the
initiative level (calendars_enabled + create_calendars), and everything inside
the calendar flows from its resource-grant DAC (``resource_grants`` +
``PUT /{id}/grants``). Events themselves carry no grants.

A calendar with no initiative is a **guild calendar** — it belongs to the guild
itself, and lives inside the calendar app. There is no initiative to gate its
creation, so guild membership is the gate: any member may make one, and what
they made is theirs to share. See ``history/guild-calendars-design.md``.
"""

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api import resource_access
from app.api.deps import (
    IncludeDeletedDep,
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import CalendarMessages, InitiativeMessages
from app.core.tools import Tool
from app.models.tenant.calendar import Calendar
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.initiative import Initiative
from app.models.platform.user import User
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.schemas.tenant.calendar import (
    CalendarCreate,
    CalendarRead,
    CalendarUpdate,
    serialize_calendar,
)
from app.services import permissions as permissions_service
from app.services.tenant import calendars as calendars_service
from app.services.tenant import guild_apps as guild_apps_service
from app.services.tenant import tags as tags_service

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_initiative_for_calendar(
    session: RLSSessionDep,
    initiative_id: int,
) -> Initiative:
    stmt = (
        select(Initiative)
        .where(Initiative.id == initiative_id)
        .options(
            selectinload(Initiative.memberships),
            selectinload(Initiative.roles),
        )
    )
    result = await session.exec(stmt)
    initiative = result.one_or_none()
    if not initiative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    return initiative


async def _refetch_calendar(session: RLSSessionDep, calendar_id: int) -> Calendar:
    calendar = await calendars_service.get_calendar(
        session, calendar_id, populate_existing=True
    )
    if not calendar:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=Tool.calendar.not_found_code,
        )
    return calendar


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/{calendar_id}", response_model=CalendarRead)
async def read_calendar(
    calendar_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    include_deleted: IncludeDeletedDep = False,
) -> CalendarRead:
    calendar = await resource_access.load_authorized(
        session, Tool.calendar, calendar_id, current_user, guild_context
    )
    return serialize_calendar(calendar, user_id=current_user.id, context=guild_context)


@router.post("/", response_model=CalendarRead, status_code=status.HTTP_201_CREATED)
async def create_calendar(
    calendar_in: CalendarCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarRead:
    """Create a calendar; the creator gets the owner grant.

    Two scopes, two gates. An **initiative** calendar needs that initiative's
    calendars switch on and the ``create_calendars`` permission (or guild
    admin). A **guild** calendar — ``initiative_id`` omitted — belongs to no
    initiative, so neither has anything to say about it: guild membership is the
    gate, which ``GuildContextDep`` has already established. What it needs
    instead is the calendar app, which is what holds it and what its removal
    takes with it.
    """
    app: Optional[GuildApp] = None
    initiative: Optional[Initiative] = None

    if calendar_in.initiative_id is None:
        # Held until this request commits, so the calendar and the app it
        # belongs to cannot part company midway: an uninstall arriving now waits
        # and takes this calendar with it.
        app = await guild_apps_service.find_mounting_app(
            session,
            guild_id=guild_context.guild_id,
            tool=Tool.calendar.value,
            for_update=True,
        )
        if app is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=CalendarMessages.GUILD_APP_REQUIRED,
            )
    else:
        initiative = await _get_initiative_for_calendar(
            session, calendar_in.initiative_id
        )
        if not initiative.calendars_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=Tool.calendar.feature_disabled_code,
            )
        await resource_access.require_create(
            session, Tool.calendar, initiative, current_user, guild_context
        )

    initiative_id = initiative.id if initiative is not None else None

    calendar = Calendar(
        initiative_id=initiative_id,
        created_by=current_user.id,
        name=calendar_in.name.strip(),
        description=calendar_in.description,
        color=calendar_in.color,
    )
    session.add(calendar)
    await session.flush()

    session.add(
        ResourceGrant(
            resource_type="calendar",
            resource_id=calendar.id,
            user_id=current_user.id,
            role_id=None,
            level=ResourceAccessLevel.owner,
            initiative_id=initiative_id,
        )
    )

    # Apply the initial sharing exactly the way edits do — one grant list, one
    # code path (defaults to Viewer for all initiative members, which at guild
    # scope reads as every member of the guild).
    await permissions_service.replace_resource_grants(
        session,
        resource_type="calendar",
        resource_id=calendar.id,
        guild_id=guild_context.guild_id,
        initiative_id=initiative_id,
        owner_id=current_user.id,
        grants=calendar_in.grants,
        actor_user_id=current_user.id,
    )

    # The app is the container, so it is answerable for this too: uninstalling
    # walks its artifacts and trashes each one.
    if app is not None:
        await guild_apps_service.record_artifact(
            session, app, artifact_type=Tool.calendar.value, artifact_id=calendar.id
        )

    if calendar_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.TOOL_TAG_LINKS[Tool.calendar],
            guild_id=guild_context.guild_id,
            entity_id=calendar.id,
            tag_ids=calendar_in.tag_ids,
        )

    await session.commit()
    hydrated = await _refetch_calendar(session, calendar.id)
    return serialize_calendar(hydrated, user_id=current_user.id, context=guild_context)


@router.patch("/{calendar_id}", response_model=CalendarRead)
async def update_calendar(
    calendar_id: int,
    calendar_in: CalendarUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarRead:
    """Rename/update a calendar. Requires write access."""
    calendar = await resource_access.load_authorized(
        session,
        Tool.calendar,
        calendar_id,
        current_user,
        guild_context,
        access="write",
    )
    updated = False
    update_data = calendar_in.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] is not None:
        calendar.name = update_data["name"].strip()
        updated = True
    if "description" in update_data:
        calendar.description = update_data["description"]
        updated = True
    if "color" in update_data and update_data["color"] is not None:
        calendar.color = update_data["color"]
        updated = True

    if updated:
        calendar.updated_at = datetime.now(timezone.utc)
        session.add(calendar)
        await session.commit()

    hydrated = await _refetch_calendar(session, calendar.id)
    return serialize_calendar(hydrated, user_id=current_user.id, context=guild_context)


@router.delete("/{calendar_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_calendar(
    calendar_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Soft-delete a calendar (cascades to its events). Requires owner
    permission or guild admin."""
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    calendar = await resource_access.load_authorized(
        session,
        Tool.calendar,
        calendar_id,
        current_user,
        guild_context,
        require_owner=True,
    )
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await soft_delete_entity(
        session,
        calendar,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Sharing (resource grants)
# ---------------------------------------------------------------------------


async def read_after_write(
    session: RLSSessionDep,
    calendar_id: int,
    user: User,
    guild_context: GuildContext,
) -> CalendarRead:
    """The calendar a write answers with: re-read after the commit, serialized.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape.
    """
    hydrated = await _refetch_calendar(session, calendar_id)
    return serialize_calendar(hydrated, user_id=user.id, context=guild_context)
