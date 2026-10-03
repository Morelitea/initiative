"""Mention syntax: parsing and anonymization.

Mention patterns in markdown — comments, task descriptions, any description:
- Users: @[](id) - e.g., @[](42), stored by id alone
  (``app.core.identity_boundary.without_mention_names``)
- Anything else: #kind[Title](id) - e.g., #task[Fix bug](123). That half is the
  reference vocabulary, read by ``app.core.references``.

An editor-state body (a document, a post, a wiki page) embeds a mention as a
Lexical ``mention`` node carrying ``mentionUserId``, with ``mentionName`` and
``text`` empty.

Content therefore holds no name for ``anonymize_user_mentions`` to take out;
it clears what a collaboration state may still hold.
"""

from typing import Set

from sqlalchemy import Text, cast
from sqlmodel import update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.identity_boundary import STORED_MENTION
from app.core.references import references_in_text
from app.core.search import SearchEntityType
from app.db import gucs
from app.db.session import raise_flag
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.db.session import routed_guild_id

# Placeholder written over an anonymized user's name in a digest row.
# Matches the frontend's rendering of anonymized users
# (``getUserDisplayName`` → "Deleted user").
ANONYMIZED_MENTION_NAME = "Deleted user"


def extract_mentioned_user_ids(content: str) -> Set[int]:
    """Extract all user IDs mentioned in the content."""
    return {int(user_id) for _, user_id in STORED_MENTION.findall(content)}


def extract_mentioned_task_ids(content: str) -> Set[int]:
    """Extract all task IDs mentioned in the content.

    Read through the reference vocabulary rather than a pattern of its own: a
    ``#`` in a comment is the same syntax wherever it is read, and it is also
    what the content-reference sync records.
    """
    return {
        entity_id
        for kind, entity_id in references_in_text(content)
        if kind is SearchEntityType.task
    }


async def anonymize_user_mentions(session: AsyncSession, *, user_id: int) -> None:
    """Take ``user_id``'s name out of the CURRENTLY ROUTED guild schema.

    Content holds none to take out: a mention is stored by id alone. A
    collaboration state can, as an editor from before names were left out
    writes one into it, and it takes precedence over the content on load. So
    every document or wiki page that mentions the user starts collaboration
    again from its content. Pending task-assignment digest rows lose the
    ``assigned_by_name`` snapshot too.

    Caller owns routing (guild-admin context), flushing order, and the commit —
    everything here rides the caller's transaction. Soft-deleted and archived
    rows are included: something restored later must not resurrect the name.
    """
    from app.services.tenant.collaboration import collaboration_manager
    from app.services.tenant.collaborative_resources import (
        YJS_STATE_COLUMN,
        registered_types,
        resource_for,
    )

    mentioned = rf'"mentionUserId":\s*{user_id}[^0-9]'

    # Finished work is included: an archived document keeps its state. Writing
    # to frozen content is the purge's kind of write, so this runs under the
    # purge flag and lowers it again before the rest of the erasure (see
    # ``app.db.gucs.PURGING``).
    await raise_flag(session, gucs.PURGING)
    rooms: list[tuple[str, int]] = []
    for kind in registered_types():
        resource = resource_for(kind)
        model = resource.model
        state = getattr(model, YJS_STATE_COLUMN)
        restarted = await session.exec(
            update(model)
            .where(
                state.is_not(None),
                cast(getattr(model, resource.content_column), Text).op("~")(mentioned),
            )
            .values({YJS_STATE_COLUMN: None})
            .returning(model.id)
            .execution_options(include_deleted=True, synchronize_session=False)
        )
        rooms.extend((kind, row_id) for row_id in restarted.scalars().all())

    # Digest rows snapshot the assigner's name for the email body.
    await session.exec(
        update(TaskAssignmentDigestItem)
        .where(TaskAssignmentDigestItem.assigned_by_id == user_id)
        .values(assigned_by_name=ANONYMIZED_MENTION_NAME)
        .execution_options(synchronize_session=False)
    )

    await session.flush()
    await raise_flag(session, gucs.PURGING, False)

    # Drop idle collaboration rooms so a room's save can't write a stale
    # in-memory state back on next disconnect. Rooms are keyed by (guild,
    # kind, id) and this runs once per guild, routed to it.
    guild_id = routed_guild_id(session)
    if guild_id is not None:
        for kind, row_id in rooms:
            await collaboration_manager.invalidate_room_if_empty(guild_id, kind, row_id)
