"""Mention syntax: parsing and anonymization.

Mention patterns in markdown — comments, task descriptions, any description:
- Users: @[Display Name](id) - e.g., @[John Doe](42)
- Anything else: #kind[Title](id) - e.g., #task[Fix bug](123). That half is the
  reference vocabulary, read by ``app.core.references``.

An editor-state body (a document, a post, a wiki page) embeds a mention as a
Lexical ``mention`` node carrying ``mentionName`` / ``mentionUserId`` /
``text``.

Both forms bake the user's display name into stored content at insert time,
so anonymizing the ``users`` row alone leaves the name readable forever.
``anonymize_user_mentions`` rewrites them to a placeholder, wherever somebody
writes.
"""

import re
from typing import Any, Set

from sqlalchemy import JSON, cast, func, text, Text
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.references import references_in_text
from app.core.search import SearchEntityType
from app.db.frozen import PURGE_GUC
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.db.session import routed_guild_id

USER_PATTERN = re.compile(r"@\[[^\]]+\]\((\d+)\)")

# Placeholder written over an anonymized user's display name wherever it was
# embedded in content. Matches the frontend's rendering of anonymized users
# (``getUserDisplayName`` → "Deleted user").
ANONYMIZED_MENTION_NAME = "Deleted user"


def extract_mentioned_user_ids(content: str) -> Set[int]:
    """Extract all user IDs mentioned in the content."""
    return {int(match) for match in USER_PATTERN.findall(content)}


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


def _markdown_mention(user_id: int) -> str:
    """A markdown mention of ``user_id``, as a regex Python and Postgres read
    alike."""
    return rf"@\[[^\]]+\]\({user_id}\)"


def _scrub_mentions(value: Any, user_id: int) -> tuple[Any, bool]:
    """``value`` with ``user_id``'s mentions reading as the placeholder — a
    Lexical mention node, or the markdown form inside any string — and whether
    anything changed."""
    pattern = re.compile(_markdown_mention(user_id))
    replacement = f"@[{ANONYMIZED_MENTION_NAME}]({user_id})"
    changed = False

    def walk(node: Any) -> Any:
        nonlocal changed
        if isinstance(node, str):
            scrubbed = pattern.sub(replacement, node)
            changed = changed or scrubbed != node
            return scrubbed
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        if node.get("mentionUserId") == user_id and (
            node.get("mentionName") != ANONYMIZED_MENTION_NAME
            or node.get("text") != ANONYMIZED_MENTION_NAME
        ):
            node = {
                **node,
                "mentionName": ANONYMIZED_MENTION_NAME,
                "text": ANONYMIZED_MENTION_NAME,
            }
            changed = True
        return {key: walk(child) for key, child in node.items()}

    return walk(value), changed


async def _set_purging(session: AsyncSession, on: bool) -> None:
    """Raise or lower the transaction-local purge flag."""
    await session.exec(
        text("SELECT set_config(:name, :value, true)").bindparams(
            name=PURGE_GUC, value="true" if on else "false"
        )
    )


async def anonymize_user_mentions(session: AsyncSession, *, user_id: int) -> None:
    """Scrub ``user_id``'s display name out of the CURRENTLY ROUTED guild schema.

    Every column somebody writes in (``search_index.written_columns`` — the
    same surfaces search reads) is searched for the user's mentions: the
    markdown form ``@[Display Name](id)`` in text, and Lexical mention nodes as
    well in an editor state. Either becomes the placeholder. A rewritten editor
    state has its ``yjs_state`` cleared, so collaboration bootstraps from the
    scrubbed content. Pending task-assignment digest rows lose the
    ``assigned_by_name`` snapshot too.

    Caller owns routing (guild-admin context), flushing order, and the commit —
    everything here rides the caller's transaction. Soft-deleted and archived
    rows are included: something restored later must not resurrect the name.
    """
    from app.db.search_index import SEARCH_SOURCES, written_columns
    from app.db.soft_delete_filter import select_including_deleted
    from app.services.tenant.collaboration import collaboration_manager
    from app.services.tenant.collaborative_resources import YJS_STATE_COLUMN

    markdown = _markdown_mention(user_id)
    replacement = f"@[{ANONYMIZED_MENTION_NAME}]({user_id})"
    # An editor state is prefiltered on its text, then decided in Python; a
    # false positive costs one no-op load.
    node = rf'"mentionUserId":\s*{user_id}[^0-9]'

    # Finished work is scrubbed too: an archived task, or a comment in the
    # trash, keeps its words and so would keep the name. Taking something that
    # has to go out of frozen content is the purge's kind of write, so the
    # scrub runs under the purge flag and lowers it again before the rest of
    # the erasure (see ``app.db.frozen.PURGE_GUC``).
    await _set_purging(session, True)
    rooms: list[tuple[SearchEntityType, int]] = []
    for model, columns in written_columns().items():
        for column in columns:
            field = getattr(model, column)
            if not isinstance(field.type, JSON):
                await session.exec(
                    update(model)
                    .where(field.op("~")(markdown))
                    .values(
                        {column: func.regexp_replace(field, markdown, replacement, "g")}
                    )
                    .execution_options(include_deleted=True, synchronize_session=False)
                )
                continue
            stmt = select_including_deleted(model).where(
                cast(field, Text).op("~")(f"{node}|{markdown}")
            )
            for row in (await session.exec(stmt)).all():
                scrubbed, changed = _scrub_mentions(getattr(row, column), user_id)
                if not changed:
                    continue
                setattr(row, column, scrubbed)
                flag_modified(row, column)
                if hasattr(model, YJS_STATE_COLUMN):
                    # Yjs state takes precedence over content on load; clear it
                    # so collaboration bootstraps from the scrubbed content.
                    setattr(row, YJS_STATE_COLUMN, None)
                    rooms.append(
                        (SEARCH_SOURCES[model.__table__.name].entity_type, row.id)
                    )
                session.add(row)

    # Digest rows snapshot the assigner's name for the email body.
    await session.exec(
        update(TaskAssignmentDigestItem)
        .where(TaskAssignmentDigestItem.assigned_by_id == user_id)
        .values(assigned_by_name=ANONYMIZED_MENTION_NAME)
        .execution_options(synchronize_session=False)
    )

    await session.flush()
    await _set_purging(session, False)

    # Drop idle collaboration rooms so a room's save can't overwrite the
    # scrubbed content with a stale in-memory copy on next disconnect. Rooms are
    # keyed by (guild, kind, id) and this runs once per guild, routed to it.
    guild_id = routed_guild_id(session)
    if guild_id is not None:
        for kind, row_id in rooms:
            await collaboration_manager.invalidate_room_if_empty(
                guild_id, kind.value, row_id
            )
