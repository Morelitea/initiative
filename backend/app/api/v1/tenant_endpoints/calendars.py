"""Calendar endpoints — the shareable container for events.

A calendar is to events what a project is to tasks: creation is gated at the
initiative level (calendars_enabled + create_calendars), and everything inside
the calendar flows from its resource-grant DAC (``resource_grants`` +
``PUT /{id}/grants``). Events themselves carry no grants.

A calendar with no initiative is a **guild calendar** — it belongs to the guild
itself, and lives inside the calendar app, whose install owns it. Guild admins
make one and decide its sharing; a member with a write grant on it writes its
events. See ``history/guild-calendars-design.md``.
"""

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    IncludeDeletedDep,
    RLSSessionDep,
    get_current_active_user,
    app_scope,
    GuildContextDep,
)
from app.core.messages import CalendarMessages, GuildMessages
from app.core.tools import Tool
from app.models.tenant.calendar import Calendar
from app.models.tenant.guild_app import GuildApp
from app.models.platform.user import User
from app.schemas.tenant.calendar import (
    CalendarCreate,
    CalendarRead,
    CalendarUpdate,
    serialize_calendar,
)
from app.services import permissions as permissions_service
from app.services.permissions import Action
from app.services.tenant import calendars as calendars_service
from app.services.tenant import guild_apps as guild_apps_service
from app.services.tenant import ownership as ownership_service
from app.services.tenant import tags as tags_service

router = APIRouter(route_class=ActorRoute)

#: The routes an installed app may call, under the calendars scopes.
CalendarsRead = Annotated[ActorContext, Depends(app_scope("calendars:read"))]
CalendarsWrite = Annotated[ActorContext, Depends(app_scope("calendars:write"))]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _refetch_calendar(session: AsyncSession, calendar_id: int) -> Calendar:
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
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CalendarsRead,
    include_deleted: IncludeDeletedDep = False,
) -> CalendarRead:
    calendar = await resource_access.load_authorized(
        session, Tool.calendar, calendar_id, current_user, guild_context
    )
    return serialize_calendar(
        calendar, user_id=guild_context.user_id, context=guild_context
    )


@router.post("/", response_model=CalendarRead, status_code=status.HTTP_201_CREATED)
async def create_calendar(
    calendar_in: CalendarCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CalendarsWrite,
) -> CalendarRead:
    """Create a calendar.

    Two scopes, two gates. An **initiative** calendar needs that initiative's
    calendars switch on and the ``create_calendars`` permission (or guild
    admin), and its creator gets the owner grant. A **guild** calendar —
    ``initiative_id`` omitted — belongs to no initiative, so neither has
    anything to say about it: it is the guild admin's to make. It needs the
    calendar app, whose install owns it and whose removal takes it along.

    An installed app creates initiative calendars only: a guild calendar is
    owned by the calendar app's install, which is community configuration.
    What it creates is owned by its install, whose owner row the table's
    trigger writes; it sets no initial sharing.
    """
    resource_access.refuse_app_sharing(guild_context, calendar_in, "grants")
    app: Optional[GuildApp] = None
    initiative_id = calendar_in.initiative_id

    if initiative_id is None and current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=CalendarMessages.APP_INITIATIVE_REQUIRED,
        )
    if initiative_id is None:
        if not guild_context.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=GuildMessages.GUILD_ADMIN_REQUIRED,
            )
        app = await guild_apps_service.find_mounting_app(
            session, tool=Tool.calendar.value
        )
        if app is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=CalendarMessages.GUILD_APP_REQUIRED,
            )
    else:
        await resource_access.prepare_create(
            session, Tool.calendar, initiative_id, current_user, guild_context
        )

    calendar = Calendar(
        initiative_id=initiative_id,
        created_by=guild_context.user_id,
        name=calendar_in.name.strip(),
        description=calendar_in.description,
        color=calendar_in.color,
    )
    session.add(calendar)
    await session.flush()

    if app is None:
        await resource_access.grant_initial_sharing(
            session,
            guild_context,
            Tool.calendar,
            user=current_user,
            resource_id=calendar.id,
            initiative_id=initiative_id,
            payload=calendar_in,
            grants=calendar_in.grants,
        )
    else:
        # The app is the container, so it owns this: uninstalling trashes what
        # the install owns. The owner grant names the install row, so an
        # uninstall holding that row finishes first and this insert fails.
        await ownership_service.set_resource_owner(
            session,
            tool=Tool.calendar,
            row=calendar,
            new_owner=ownership_service.Owner(app_install_id=app.id),
        )
        # The default sharing, at guild scope, reads as every member of the guild.
        await permissions_service.replace_resource_grants(
            session,
            resource_type=Tool.calendar.value,
            resource_id=calendar.id,
            guild_id=guild_context.guild_id,
            initiative_id=None,
            owner_id=None,
            grants=calendar_in.grants,
            actor_user_id=guild_context.user_id,
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
    return serialize_calendar(
        hydrated, user_id=guild_context.user_id, context=guild_context
    )


@router.patch("/{calendar_id}", response_model=CalendarRead)
async def update_calendar(
    calendar_id: int,
    calendar_in: CalendarUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CalendarsWrite,
) -> CalendarRead:
    """Rename/update a calendar. Asks the edit action, which on a guild
    calendar is the guild admin's: a write grant on one writes its events."""
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
    return serialize_calendar(
        hydrated, user_id=guild_context.user_id, context=guild_context
    )


@router.delete("/{calendar_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_calendar(
    calendar_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Soft-delete a calendar (cascades to its events). Requires owner
    permission or guild admin."""
    from app.services.tenant.soft_delete import trash

    calendar = await resource_access.load_authorized(
        session,
        Tool.calendar,
        calendar_id,
        current_user,
        guild_context,
        action=Action.delete,
    )
    await trash(
        session,
        calendar,
        deleted_by_user_id=current_user.id,
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Sharing (resource grants)
# ---------------------------------------------------------------------------


async def read_after_write(
    session: RLSSessionDep,
    calendar_id: int,
    user: Optional[User],
    guild_context: ActorContext,
) -> CalendarRead:
    """The calendar a write answers with: re-read after the commit, serialized.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape.
    """
    hydrated = await _refetch_calendar(session, calendar_id)
    return serialize_calendar(
        hydrated, user_id=guild_context.user_id, context=guild_context
    )
