"""Who each name in a bundle is, in the community it is being imported into.

An envelope names people by **handle** — ``foobar#1234``, the one identifier
that means the same thing in every community — because an id means nothing on
the far side and an address is not a person's identifier here. Matching those
handles to real accounts is the one part of an import nobody can do from the
data alone: two people can carry the same display name, one person can carry
different handles on two servers, and an export from somewhere else carries
names that were never accounts here at all.

So it is asked, not guessed. The plan lists every person the bundle mentions
with a suggestion where an exact handle matched, the importer confirms or
changes each row in the wizard, and the confirmed answer is what this map
holds. A row left unmapped stays unmapped: a name nobody claimed is reported,
never attached to whoever looked closest.

The mapping is re-checked here, at apply time, against real guild membership
on the caller's own routed session — the confirm may have been hours ago, and
somebody named in it may have left since.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.import_engine.common import handle_key

logger = logging.getLogger(__name__)


@dataclass
class PeopleMap:
    """Source handle → the account it was confirmed to be.

    Empty is the ordinary case, not a failure: an import nobody mapped anybody
    for behaves exactly as it did before there was a mapping step.
    """

    _by_handle: dict[str, int] = field(default_factory=dict)

    def user_id(self, handle: str | None) -> int | None:
        """The account this handle was mapped to, or None if nobody claimed
        it. A handle matches however it was capitalised, because a handle is
        one name however it is typed."""
        if not handle:
            return None
        return self._by_handle.get(handle_key(handle))

    def __bool__(self) -> bool:
        return bool(self._by_handle)

    def __len__(self) -> int:
        return len(self._by_handle)


async def resolve_people_map(
    session: AsyncSession, *, guild_id: int, raw: Any
) -> PeopleMap:
    """Build the map the importers read from what the confirm recorded.

    ``raw`` is ``{source_handle: user_id}`` as it was stored on the job row,
    so it is JSON that round-tripped through a request: every value is
    validated rather than trusted. An id naming somebody who is not a member
    of this guild **now** is dropped and logged — the confirm proved they were
    reachable when it was made, and this proves it again at the moment the
    rows are actually written.
    """
    if not isinstance(raw, dict) or not raw:
        return PeopleMap()

    wanted: dict[str, int] = {}
    for source_handle, user_id in raw.items():
        if not isinstance(source_handle, str):
            continue
        try:
            wanted[handle_key(source_handle)] = int(user_id)
        except (TypeError, ValueError):
            continue
    if not wanted:
        return PeopleMap()

    members = set(
        await guild_member_ids(
            session, guild_id=guild_id, user_ids=set(wanted.values())
        )
    )
    resolved = {
        handle: user_id for handle, user_id in wanted.items() if user_id in members
    }
    dropped = len(wanted) - len(resolved)
    if dropped:
        logger.info(
            "import people map dropped %s entr%s naming non-members guild=%s",
            dropped,
            "y" if dropped == 1 else "ies",
            guild_id,
        )
    return PeopleMap(resolved)


async def guild_member_ids(
    session: AsyncSession, *, guild_id: int, user_ids: set[int]
) -> list[int]:
    """Which of these accounts are members of this guild, as the caller can
    see it. Read on the routed session, so RLS answers the question."""
    from app.models.platform.guild import GuildMembership

    if not user_ids:
        return []
    return list(
        await session.exec(
            select(GuildMembership.user_id).where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id.in_(user_ids),
            )
        )
    )


def initiative_member_id(
    handle: str | None,
    *,
    people: PeopleMap,
    member_handles: Mapping[str, int],
    member_ids: frozenset[int],
) -> int | None:
    """Which member of the target initiative a source handle names.

    Two ways to answer it, and the initiative's own roster gates both:

    1. The account somebody mapped this handle to in the wizard's people step.
    2. A member whose handle is the same string.

    That gate is the whole difference between this and the rule authorship
    follows (``_comment_author`` in ``services.tenant.project_import``). Being
    quoted as the author of a comment is a fact about the past and can be
    recorded about anybody the community knows; being assigned a task is a
    statement about who is working on something here, now, and only the
    initiative's roster can answer it. So the map says *which account* a
    handle means — it never puts somebody into an initiative they are not in.

    Returns ``None`` when neither answer lands, and the caller counts the
    handle as unmatched.
    """
    if not handle:
        return None
    mapped = people.user_id(handle)
    if mapped is not None and mapped in member_ids:
        return mapped
    return member_handles.get(handle_key(handle))


def quoted_account(
    handle: str | None,
    *,
    people: PeopleMap,
    member_handles: Mapping[str, int],
) -> int | None:
    """Who a handle quoted in some writing — its author, somebody it
    mentions — is here.

    The account the people step mapped it to, else a member of the target
    initiative whose handle is the same string. Unlike
    :func:`initiative_member_id` the mapped account need not be in the
    initiative: who wrote or was named in something is a fact about the past,
    and can be recorded about anybody the community knows.
    """
    if not handle:
        return None
    mapped = people.user_id(handle)
    if mapped is not None:
        return mapped
    return member_handles.get(handle_key(handle))


def user_reference_handles(payload: Any) -> list[str]:
    """Every handle a user-type property value in ``payload`` names.

    ``payload`` is an envelope as plain data — a dict from a zip, or a model
    dumped to JSON — walked whole, because property values sit at different
    depths in different tools' envelopes (a task's, a document's, an event's)
    and all of them are the same shape: ``property_type`` of
    ``user_reference`` beside a ``value_handle``.

    First-seen order, one entry per person, keyed the way handles are
    matched. It is the inventory half of the people step: whoever a value
    names has to be asked about, or it resolves by name alone.
    """
    found: dict[str, str] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("property_type") == "user_reference":
                handle = node.get("value_handle")
                if isinstance(handle, str) and handle.strip():
                    found.setdefault(handle_key(handle), handle.strip())
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return list(found.values())
