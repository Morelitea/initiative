"""What every area of the dev seed shares: the clock, the community being
seeded, and the helpers each tool's rows are built with."""

from __future__ import annotations

import zlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.guild import Guild
from app.models.platform.user import User
from app.models.tenant._mixins import ArchiveMixin
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.counter import CounterGroup
from app.models.tenant.document import Document
from app.models.tenant.initiative import Initiative, InitiativeRoleModel
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.tenant.tag import Tag
from app.models.tenant.task import Task
from app.services.tenant import tags as tags_service

#: One "now" for the whole run, so every relative date in it agrees.
NOW = datetime.now(timezone.utc)


def days_ago(days: int) -> datetime:
    """How a seeded picture is dated, so a wall has months for the timeline
    rail to scrub through rather than everything arriving at once."""
    return NOW - timedelta(days=days)


@dataclass
class Community:
    """One community being seeded, and what its later steps need from its
    earlier ones.

    ``key`` picks this community's rows out of each area's tables. Initiatives
    and their member roles are keyed by the seed's own short names; everything
    else by the title the tables use for it.
    """

    key: str
    session: AsyncSession
    ids: dict[str, list]
    users: dict[str, User]
    guild: Guild
    initiatives: dict[str, Initiative] = field(default_factory=dict)
    member_roles: dict[str, InitiativeRoleModel] = field(default_factory=dict)
    tags: dict[str, Tag] = field(default_factory=dict)
    projects: dict[str, Project] = field(default_factory=dict)
    tasks: dict[str, Task] = field(default_factory=dict)
    docs: dict[str, Document] = field(default_factory=dict)
    counter_groups: dict[str, CounterGroup] = field(default_factory=dict)
    events: dict[str, CalendarEvent] = field(default_factory=dict)
    #: Rows to archive, and the date to stamp, once the community is filled.
    archives: list[tuple[ArchiveMixin, datetime]] = field(default_factory=list)


def share(
    c: Community,
    tool: Tool,
    row: SQLModel,
    owner: User,
    *,
    writers: Iterable[str] = (),
    readers: Iterable[str] = (),
    roles: Iterable[tuple[str, ResourceAccessLevel]] = (),
    general: ResourceAccessLevel | None = None,
) -> None:
    """The owner grant, and whatever sharing a table row asks for.

    ``writers``/``readers`` are people by name, ``roles`` is ``(initiative key,
    level)`` for that initiative's member role, and ``general`` is the
    all-initiative-members grant. None of them leaves the row private.
    """

    def grant(level: ResourceAccessLevel, **grantee: object) -> None:
        c.session.add(
            ResourceGrant(
                resource_type=tool.value,
                resource_id=row.id,
                initiative_id=row.initiative_id,
                level=level,
                **grantee,
            )
        )

    grant(ResourceAccessLevel.owner, user_id=owner.id)
    for names, level in (
        (writers, ResourceAccessLevel.write),
        (readers, ResourceAccessLevel.read),
    ):
        for name in names:
            if c.users[name].id != owner.id:
                grant(level, user_id=c.users[name].id)
    for key, level in roles:
        grant(level, role_id=c.member_roles[key].id)
    if general is not None:
        grant(general, all_initiative_members=True)


def tag(c: Community, row: SQLModel, names: Iterable[str]) -> None:
    """Label ``row`` with the community's tags, as the edges the app stores."""
    spec = tags_service.spec_for(row)
    for name in names:
        c.session.add(tags_service.tag_edge(spec, row.id, c.tags[name].id))


# --- Lexical bodies ---------------------------------------------------------


def para(text: str) -> dict:
    """One paragraph, as the editor serializes one."""
    return {"children": [{"text": text, "type": "text"}], "type": "paragraph"}


def heading(text: str, level: int = 2) -> dict:
    """One heading. The contents list in the sidebar is built from these."""
    return {
        "children": [{"text": text, "type": "text"}],
        "type": "heading",
        "tag": f"h{level}",
    }


def lexical(children: list[dict]) -> dict:
    """An editor document holding ``children``."""
    return {"root": {"children": children, "type": "root"}}


def chip(entity_type: str, entity_id: int, text: str) -> dict:
    """A live smart chip, as the editor serializes one.

    Only the three fields ``EntityMentionNode.importJSON`` reads. A chip shows
    a fact ABOUT the thing it names and keeps showing the current one.
    """
    return {
        "type": "entity-mention",
        "version": 1,
        "entityType": entity_type,
        "entityId": entity_id,
        "text": text,
    }


def gradient_png(
    width: int, height: int, top: tuple[int, int, int], bottom: tuple[int, int, int]
) -> bytes:
    """A vertical-gradient PNG, written by hand so seeding needs no image library.

    Every row is one flat colour, which is what keeps the result a few KB
    instead of the megabytes its raw pixels would be — well inside the caps in
    ``IMAGE_SPECS``.
    """
    raw = bytearray()
    for y in range(height):
        ratio = y / max(height - 1, 1)
        pixel = bytes(
            round(start + (end - start) * ratio) for start, end in zip(top, bottom)
        )
        raw.append(0)  # per-scanline filter: none
        raw.extend(pixel * width)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            len(payload).to_bytes(4, "big")
            + kind
            + payload
            + zlib.crc32(kind + payload).to_bytes(4, "big")
        )

    header = (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes((8, 2, 0, 0, 0))  # 8-bit truecolour, no interlace
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
