"""Mention syntax: parsing and anonymization.

Mention patterns in comment text:
- Users: @[Display Name](id) - e.g., @[John Doe](42)
- Tasks: #task[Title](id) - e.g., #task[Fix bug](123)

Native documents embed mentions differently — as Lexical ``mention`` nodes
carrying ``mentionName`` / ``mentionUserId`` / ``text`` in the content JSON.

Both forms bake the user's display name into stored content at insert time,
so anonymizing the ``users`` row alone leaves the name readable forever.
``anonymize_user_mentions`` rewrites them to a placeholder.
"""

import re
from copy import deepcopy
from typing import Any, Set

from sqlalchemy import cast, func, Text
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.comment import Comment
from app.models.tenant.document import Document
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem

USER_PATTERN = re.compile(r"@\[[^\]]+\]\((\d+)\)")
TASK_PATTERN = re.compile(r"#task\[[^\]]+\]\((\d+)\)")

# Placeholder written over an anonymized user's display name wherever it was
# embedded in content. Matches the frontend's rendering of anonymized users
# (``getUserDisplayName`` → "Deleted user").
ANONYMIZED_MENTION_NAME = "Deleted user"


def extract_mentioned_user_ids(content: str) -> Set[int]:
    """Extract all user IDs mentioned in the content."""
    return {int(match) for match in USER_PATTERN.findall(content)}


def extract_mentioned_task_ids(content: str) -> Set[int]:
    """Extract all task IDs mentioned in the content."""
    return {int(match) for match in TASK_PATTERN.findall(content)}


def _scrub_mention_nodes(content: dict[str, Any], user_id: int) -> bool:
    """Rewrite Lexical mention nodes for ``user_id`` to the placeholder name.

    Returns True if any node changed.
    """
    changed = False

    def walk(node: Any) -> None:
        nonlocal changed
        if not isinstance(node, dict):
            return
        if (
            node.get("type") in ("mention", "custom-mention")
            and node.get("mentionUserId") == user_id
        ):
            if (
                node.get("mentionName") != ANONYMIZED_MENTION_NAME
                or node.get("text") != ANONYMIZED_MENTION_NAME
            ):
                node["mentionName"] = ANONYMIZED_MENTION_NAME
                node["text"] = ANONYMIZED_MENTION_NAME
                changed = True
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                walk(child)

    root = content.get("root")
    if isinstance(root, dict):
        walk(root)

    return changed


async def anonymize_user_mentions(session: AsyncSession, *, user_id: int) -> None:
    """Scrub ``user_id``'s display name out of the CURRENTLY ROUTED guild schema.

    Three places embed the name as literal content rather than referencing the
    ``users`` row (which the anonymize wipe already handles):

    - comment text: ``@[Display Name](id)`` → ``@[Deleted user](id)``
    - native-document Lexical ``mention`` nodes: ``mentionName``/``text``
      → the placeholder (``yjs_state`` cleared so collaboration bootstraps
      from the rewritten content, mirroring the wikilink-unresolve path)
    - pending task-assignment digest rows: the ``assigned_by_name`` snapshot

    Caller owns routing (guild-admin context), flushing order, and the commit —
    everything here rides the caller's transaction. Soft-deleted rows are
    included: a trashed comment or document restored later must not resurrect
    the name.
    """
    from app.db.soft_delete_filter import select_including_deleted
    from app.services.tenant.collaboration import collaboration_manager

    # Comment text — one UPDATE, filtered and rewritten by the same pattern.
    # (POSIX regex, applied in Postgres; parameterized, nothing interpolated
    # except the numeric id.)
    pattern = rf"@\[[^\]]+\]\({user_id}\)"
    replacement = f"@[{ANONYMIZED_MENTION_NAME}]({user_id})"
    await session.exec(
        update(Comment)
        .where(Comment.content.op("~")(pattern))
        .values(content=func.regexp_replace(Comment.content, pattern, replacement, "g"))
        .execution_options(include_deleted=True, synchronize_session=False)
    )

    # Document mention nodes. The text-cast regex is only a prefilter — the
    # Python walk makes the actual decision, so a false positive costs one
    # no-op load. ``select_including_deleted`` covers trashed documents.
    prefilter = rf'"mentionUserId":\s*{user_id}[^0-9]'
    stmt = select_including_deleted(Document).where(
        cast(Document.content, Text).op("~")(prefilter)
    )
    documents = (await session.exec(stmt)).all()

    affected_doc_ids: list[int] = []
    for doc in documents:
        if not isinstance(doc.content, dict):
            continue
        updated_content = deepcopy(doc.content)
        if _scrub_mention_nodes(updated_content, user_id):
            doc.content = updated_content
            # Yjs state takes precedence over content on load; clear it so
            # collaboration bootstraps from the scrubbed content.
            doc.yjs_state = None
            flag_modified(doc, "content")
            session.add(doc)
            affected_doc_ids.append(doc.id)

    # Digest rows snapshot the assigner's name for the email body.
    await session.exec(
        update(TaskAssignmentDigestItem)
        .where(TaskAssignmentDigestItem.assigned_by_id == user_id)
        .values(assigned_by_name=ANONYMIZED_MENTION_NAME)
        .execution_options(synchronize_session=False)
    )

    await session.flush()

    # Drop idle collaboration rooms so persist_room can't overwrite the
    # scrubbed content with a stale in-memory copy on next disconnect.
    for doc_id in affected_doc_ids:
        await collaboration_manager.invalidate_room_if_empty(doc_id)
