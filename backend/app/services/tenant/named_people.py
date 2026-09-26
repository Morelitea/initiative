"""Who may be named on a piece of content.

A task's assignees, an event's attendees, a person-valued property and a queue
item's person all name somebody on a row that lives inside a tool. Whoever is
named must be able to open that tool's row: the rule is the same for all of
them, and it is asked here.

"Able to open" is the database's own answer for that person, restated for a
person other than the one asking. The policies read the requester's standing,
so they cannot answer about somebody else; this spells the same gates over the
tables the standing is computed from:

- the account is in the community and not absent (suspended, or leaving);
- a community admin opens everything;
- anyone else, for a row of an initiative: they are its member, the tool is
  switched on there, their role lets them view the tool, and the row's sharing
  reaches them (a grant naming them, their role, or every member) or their role
  sees past sharing;
- for a row of the community itself (a guild calendar): its sharing reaches
  them.

``named_people_test`` holds this to what the database answers when the person
opens the row themselves.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, false, or_, true
from sqlalchemy import Select
from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy import select as sa_select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import CommonMessages
from app.core.tools import DEFAULT_ENABLED_TOOLS, Tool
from app.db import cohorts
from app.db.session import install_context, routed_guild_id, set_rls_context
from app.models.platform.guild import GUILD_LADDER, GuildMembership, GuildRole
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.initiative import (
    Initiative,
    InitiativeMember,
    InitiativeRoleModel,
    InitiativeRolePermission,
)
from app.models.tenant.calendar_event import CalendarEvent, CalendarEventAttendee
from app.models.tenant.property import (
    CalendarEventPropertyValue,
    DocumentPropertyValue,
    TaskPropertyValue,
)
from app.models.tenant.queue import QueueItem
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.task import Task, TaskAssignee
from app.services.platform.users import visible_to_other_people

_ADMIN_RUNGS = [rung for rung in GUILD_LADDER if rung.reaches(GuildRole.admin)]


@dataclass(frozen=True)
class Governing:
    """The tool row whose sharing decides who may be named on content inside
    it: a task's project, an event's calendar, a document itself."""

    tool: Tool
    resource_id: int
    initiative_id: Optional[int]

    @classmethod
    def of(cls, tool: Tool, row: Any) -> "Governing":
        return cls(tool, row.id, row.initiative_id)


def _grant_reaches(
    governing: Governing, user_id: Any, *outer: Any
) -> ColumnElement[bool]:
    """A grant on the row that reaches ``user_id``: naming them, on a role
    they hold, or shared with every member of an initiative they are in (or of
    the community, on a row that belongs to none)."""
    im = aliased(InitiativeMember)
    held = sa_select(im.role_id).where(im.user_id == user_id).correlate(*outer)
    joined = sa_select(im.initiative_id).where(im.user_id == user_id).correlate(*outer)
    return (
        exists()
        .where(
            ResourceGrant.resource_type == governing.tool.value,
            ResourceGrant.resource_id == governing.resource_id,
            or_(
                ResourceGrant.user_id == user_id,
                ResourceGrant.role_id.in_(held),
                and_(
                    ResourceGrant.all_initiative_members.is_(True),
                    or_(
                        ResourceGrant.initiative_id.is_(None),
                        ResourceGrant.initiative_id.in_(joined),
                    ),
                ),
            ),
        )
        .correlate(*outer)
    )


def readers_of(governing: Governing, guild_id: int) -> Select:
    """The ids of everyone who can open the governing row, as a subquery."""
    tool = governing.tool
    gm = aliased(GuildMembership)
    present = (
        exists()
        .where(
            MemberProfile.id == gm.user_id,
            visible_to_other_people(MemberProfile.status),
        )
        .correlate(gm)
    )
    if governing.initiative_id is None:
        reached = _grant_reaches(governing, gm.user_id, gm)
    else:
        im = aliased(InitiativeMember)
        role = aliased(InitiativeRoleModel)
        default = true() if tool in DEFAULT_ENABLED_TOOLS else false()

        def role_says(enabled: bool) -> ColumnElement[bool]:
            return (
                exists()
                .where(
                    InitiativeRolePermission.initiative_role_id == im.role_id,
                    InitiativeRolePermission.permission_key == tool.view_permission,
                    InitiativeRolePermission.enabled.is_(enabled),
                )
                .correlate(im)
            )

        reached = exists(
            sa_select(1)
            .select_from(im)
            .join(Initiative, Initiative.id == im.initiative_id)
            .outerjoin(role, role.id == im.role_id)
            .where(
                im.initiative_id == governing.initiative_id,
                im.user_id == gm.user_id,
                getattr(Initiative, f"{tool.plural}_enabled").is_(True),
                or_(
                    role.is_manager.is_(True),
                    role_says(True),
                    and_(default, ~role_says(False)),
                ),
                or_(
                    role.override_share_restrictions.is_(True),
                    _grant_reaches(governing, gm.user_id, gm, im),
                ),
            )
            .correlate(gm)
        )
    return sa_select(gm.user_id).where(
        gm.guild_id == guild_id,
        present,
        or_(gm.role.in_(_ADMIN_RUNGS), reached),
    )


@asynccontextmanager
async def roster_session(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Where the routed community's roster is read for ``session``'s request.

    The request's own session for a person, so a row it has just made is seen.
    An installed app's role reads as much of the roster as its scopes allow,
    and who can open something is not its scopes' to say, so its requests are
    answered by the community's own read instead, as
    :mod:`app.services.reachability` does.
    """
    if install_context(session) is None:
        yield session
        return
    guild_id = routed_guild_id(session)
    async with cohorts.system_session(guild_id) as probe, probe.begin():
        await set_rls_context(probe, guild_id=guild_id)
        yield probe


async def readers(
    session: AsyncSession, governing: Governing, user_ids: Iterable[int]
) -> set[int]:
    """Those of ``user_ids`` who can open the governing row, read on
    :func:`roster_session`."""
    ids = sorted(set(user_ids))
    if not ids:
        return set()
    guild_id = routed_guild_id(session)
    if guild_id is None:
        raise RuntimeError("people are named on content inside a community")
    stmt = select(MemberProfile.id).where(
        MemberProfile.id.in_(ids),
        MemberProfile.id.in_(readers_of(governing, guild_id)),
    )
    async with roster_session(session) as reader:
        return set((await reader.exec(stmt)).all())


async def require_readers(
    session: AsyncSession, governing: Governing, user_ids: Iterable[int]
) -> None:
    """Refuse (422 ``PERSON_CANNOT_READ``) unless everyone in ``user_ids`` can
    open the governing row."""
    wanted = set(user_ids)
    if wanted - await readers(session, governing, wanted):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=CommonMessages.PERSON_CANNOT_READ,
        )


# --- Where content names somebody --------------------------------------------


@dataclass(frozen=True)
class PersonRef:
    """A column naming a person on content inside a tool. ``within`` picks the
    rows inside one governing row; ``clears`` empties the column rather than
    deleting the row, where the row is more than the name (a property value,
    a queue item)."""

    column: Any
    within: Callable[[int], ColumnElement[bool]]
    clears: bool = False


#: Every person column, by the tool whose sharing decides who it may name.
PERSON_REFS: dict[Tool, tuple[PersonRef, ...]] = {
    Tool.project: (
        PersonRef(
            TaskAssignee.user_id,
            lambda pid: TaskAssignee.task_id.in_(
                sa_select(Task.id).where(Task.project_id == pid)
            ),
        ),
        PersonRef(
            TaskPropertyValue.value_user_id,
            lambda pid: TaskPropertyValue.task_id.in_(
                sa_select(Task.id).where(Task.project_id == pid)
            ),
            clears=True,
        ),
    ),
    Tool.calendar: (
        PersonRef(
            CalendarEventAttendee.user_id,
            lambda cid: CalendarEventAttendee.calendar_event_id.in_(
                sa_select(CalendarEvent.id).where(CalendarEvent.calendar_id == cid)
            ),
        ),
        PersonRef(
            CalendarEventPropertyValue.value_user_id,
            lambda cid: CalendarEventPropertyValue.event_id.in_(
                sa_select(CalendarEvent.id).where(CalendarEvent.calendar_id == cid)
            ),
            clears=True,
        ),
    ),
    Tool.document: (
        PersonRef(
            DocumentPropertyValue.value_user_id,
            lambda did: DocumentPropertyValue.document_id == did,
            clears=True,
        ),
    ),
    Tool.queue: (
        PersonRef(
            QueueItem.user_id, lambda qid: QueueItem.queue_id == qid, clears=True
        ),
    ),
}


async def named_on(session: AsyncSession, governing: Governing) -> set[int]:
    """Everyone the content inside the governing row names."""
    named: set[int] = set()
    for ref in PERSON_REFS.get(governing.tool, ()):
        named.update(
            (
                await session.exec(
                    select(ref.column)
                    .where(ref.within(governing.resource_id), ref.column.is_not(None))
                    .distinct()
                )
            ).all()
        )
    return named


async def sweep(session: AsyncSession, governing: Governing) -> set[int]:
    """Take everyone who cannot open the governing row off the content inside
    it, and answer who that was."""
    named = await named_on(session, governing)
    gone = named - await readers(session, governing, named)
    if not gone:
        return gone
    for ref in PERSON_REFS.get(governing.tool, ()):
        table = ref.column.class_
        where = (ref.within(governing.resource_id), ref.column.in_(gone))
        await session.exec(
            sa_update(table).where(*where).values({ref.column.key: None})
            if ref.clears
            else sa_delete(table).where(*where)
        )
    return gone
