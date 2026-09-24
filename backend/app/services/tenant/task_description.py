"""What saving a task's description sets in motion.

A description is written in the same composer as a comment, so it carries the
same mention syntax: ``@[Name](id)`` for a person, ``#kind[Title](id)`` for a
thing. Saving one does two things with those:

* the ``#`` references become the task's ``references`` edges, recomputed from
  the description and the task's comments together
  (:mod:`app.services.tenant.content_references`);
* each person the description names *for the first time* hears about it. A
  mention that was already there when the description was last saved is not
  news, so editing a sentence around it does not notify again.

Only members of the task's initiative are told — the mention picker offers
nobody else, and a notice names the task to whoever gets it.
"""

from __future__ import annotations

from typing import cast

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.search import SearchEntityType
from app.models.platform.user import User
from app.models.tenant.task import Task
from app.services import notifications as notifications_service
from app.services.platform import accounts as accounts_service
from app.services.tenant import content_references
from app.services.tenant import initiatives as initiatives_service
from app.services.tenant.mention_parser import extract_mentioned_user_ids
from app.services.tenant.relationships import Endpoint


def newly_mentioned(description: str | None, previous: str | None) -> set[int]:
    """The people ``description`` names that ``previous`` did not."""
    return extract_mentioned_user_ids(description or "") - extract_mentioned_user_ids(
        previous or ""
    )


async def record_references(
    session: AsyncSession, task: Task, *, author_id: int | None
) -> None:
    """Make the task's ``references`` edges match its description and comments.

    On its own for a copy of text somebody already wrote — a duplicated task
    points at what its original did, and names nobody anew.
    """
    await content_references.sync_for_entity(
        session,
        Endpoint(SearchEntityType.task, cast(int, task.id)),
        body=task.description,
        author_id=author_id,
    )


async def description_saved(
    session: AsyncSession,
    task: Task,
    *,
    previous: str | None,
    author: User | None,
    guild_id: int,
    initiative_id: int,
) -> None:
    """Record what the description now points at, and tell whoever it newly
    names.

    ``previous`` is the description as it stood before this save — ``None`` for
    a task that is new. ``author`` is ``None`` for an installed app, whose
    save records references and tells nobody: a mention names a person by
    their row id, which an app does not hold. Rides the caller's transaction;
    the caller commits.
    """
    await record_references(
        session, task, author_id=author.id if author is not None else None
    )
    if author is None:
        return

    added = newly_mentioned(task.description, previous)
    added.discard(author.id)
    if not added:
        return

    roster = await initiatives_service.initiative_roster(session, initiative_id)
    member_ids = {membership.user_id for membership in roster if membership.user_id}
    # Who to tell is a question about their account, so it is asked where an
    # account may be read.
    recipients = await accounts_service.load(
        (user_id for user_id in added if user_id in member_ids),
        excluding_ignorers_of=author.id,
    )
    for user_id in sorted(recipients):
        await notifications_service.notify_task_description_mention(
            session,
            mentioned_user=recipients[user_id],
            mentioned_by=author,
            task_id=cast(int, task.id),
            task_title=task.title,
            guild_id=guild_id,
            initiative_id=initiative_id,
        )
