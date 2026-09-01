"""Emoji reactions on anything reactable.

One table, one service, one set of endpoints for every kind of target. The
registry below is the only place a kind is wired: it says how to load the
target, how to authorize a reaction on it, and what a notification about it
should say. Comments are the first (and today only) member; a feed post joins
by adding a ``ReactionTarget`` member and one entry here.

**Access.** Reacting asks for ``write`` on the thing being reacted to, exactly
as posting a comment does — one gate, one answer, so a surface can never show a
reaction control where it would not show a reply box. Seeing the chips asks for
``read``, so a read-only PAM window can look without leaving a mark.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional, cast

from sqlalchemy import String, bindparam, delete as sa_delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ReactionMessages
from app.core.reactions import ReactionTarget
from app.models.tenant.comment import Comment
from app.models.tenant.reaction import Reaction
from app.models.platform.user import User
from app.schemas.tenant.reaction import ReactionGroup, ReactionSummary, ReactionUser

logger = logging.getLogger(__name__)

#: How many reactors a group names. The chip shows a face pile / tooltip, not a
#: roster, and the count is always the whole truth.
MAX_NAMED_REACTORS = 8

#: A ceiling per person per target, so one account cannot turn a comment into
#: an unbounded list of chips.
MAX_REACTIONS_PER_USER = 20


#: Bind parameter for the toggle lock key — bound, never interpolated.
_TOGGLE_KEY = bindparam("toggle_key", type_=String)


class ReactionError(Exception):
    """Base error for reaction operations."""


class ReactionNotFoundError(ReactionError):
    """The target does not exist (or is not visible)."""


class ReactionPermissionError(ReactionError):
    """The user may not react here."""


class ReactionValidationError(ReactionError):
    """The payload is refused."""


@dataclass(frozen=True)
class TargetContext:
    """A loaded, authorized reaction target.

    ``title`` labels it in a notification, ``target_path`` is where a tap on
    that notification lands, and ``author_id`` is who hears about the reaction
    (None when nobody should).
    """

    target: ReactionTarget
    target_id: int
    title: str
    target_path: str
    author_id: Optional[int]


#: Resolver signature: load + authorize one target, or raise.
Resolver = Callable[[AsyncSession, int, User, int, str], Awaitable["TargetContext"]]


async def _resolve_comment(
    session: AsyncSession,
    target_id: int,
    user: User,
    guild_id: int,
    access: str,
) -> TargetContext:
    """A comment is reachable exactly as its own thread is, and writable
    exactly as the thread is postable — the comments service already owns both
    decisions, so it makes them here too."""
    from app.services.tenant import comments as comments_service

    try:
        comment, ctx = await comments_service.get_comment_with_parent(
            session,
            comment_id=target_id,
            user=user,
            guild_id=guild_id,
            access=access,
        )
    except comments_service.CommentNotFoundError as exc:
        raise ReactionNotFoundError(ReactionMessages.TARGET_NOT_FOUND) from exc
    except comments_service.CommentPermissionError as exc:
        raise ReactionPermissionError(ReactionMessages.PERMISSION_DENIED) from exc

    return TargetContext(
        target=ReactionTarget.comment,
        target_id=cast(int, comment.id),
        title=ctx.title,
        target_path=comments_service.comment_target_path(comment, ctx),
        author_id=comment.created_by,
    )


#: Every reactable kind -> how to load and authorize it. The single wiring point.
TARGET_RESOLVERS: dict[ReactionTarget, Resolver] = {
    ReactionTarget.comment: _resolve_comment,
}


async def resolve_target(
    session: AsyncSession,
    *,
    target: ReactionTarget,
    target_id: int,
    user: User,
    guild_id: int,
    access: str = "read",
) -> TargetContext:
    """Load + authorize one reaction target at ``access`` level."""
    return await TARGET_RESOLVERS[target](session, target_id, user, guild_id, access)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


async def load_reactions(
    session: AsyncSession,
    *,
    target: ReactionTarget,
    target_ids: Sequence[int],
) -> dict[int, list[Reaction]]:
    """Every reaction on each of ``target_ids``, oldest first.

    One query for a whole thread: the comment list serializes its reactions
    from this rather than asking per row. RLS has already decided which of
    these rows the request may see.
    """
    if not target_ids:
        return {}
    rows = (
        await session.exec(
            select(Reaction)
            .where(
                Reaction.target_type == target.value,
                Reaction.target_id.in_(tuple(target_ids)),
            )
            .order_by(Reaction.created_at.asc(), Reaction.id.asc())
            .options(selectinload(Reaction.reactor))
        )
    ).all()
    grouped: dict[int, list[Reaction]] = {target_id: [] for target_id in target_ids}
    for row in rows:
        grouped.setdefault(row.target_id, []).append(row)
    return grouped


def summarize(
    reactions: Iterable[Reaction], *, viewer_id: Optional[int]
) -> list[ReactionGroup]:
    """Collapse rows into one group per emoji, in first-reacted order.

    Ordering by when an emoji first appeared (rather than by count) keeps the
    chips from reshuffling under the cursor as counts change.
    """
    groups: dict[str, ReactionGroup] = {}
    for reaction in reactions:
        group = groups.get(reaction.emoji)
        if group is None:
            group = ReactionGroup(emoji=reaction.emoji, count=0)
            groups[reaction.emoji] = group
        group.count += 1
        if reaction.created_by == viewer_id:
            group.reacted = True
        if len(group.users) < MAX_NAMED_REACTORS and reaction.reactor is not None:
            group.users.append(ReactionUser.model_validate(reaction.reactor))
    return list(groups.values())


async def summary_for(
    session: AsyncSession,
    *,
    target: ReactionTarget,
    target_id: int,
    viewer_id: Optional[int],
) -> ReactionSummary:
    """The whole reaction state of one target, as the toggle route replies."""
    grouped = await load_reactions(session, target=target, target_ids=[target_id])
    return ReactionSummary(
        target_type=target,
        target_id=target_id,
        groups=summarize(grouped.get(target_id, []), viewer_id=viewer_id),
    )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


async def toggle_reaction(
    session: AsyncSession,
    *,
    target: ReactionTarget,
    target_id: int,
    emoji: str,
    user: User,
    guild_id: int,
) -> tuple[ReactionSummary, bool]:
    """Add the user's ``emoji`` to a target, or take it back if it is there.

    Returns the target's full reaction state plus whether this call ADDED one —
    the caller needs that to decide whether anyone should be notified.
    """
    ctx = await resolve_target(
        session,
        target=target,
        target_id=target_id,
        user=user,
        guild_id=guild_id,
        access="write",
    )

    # A toggle is one decision made of three statements — is it there, take it
    # back or put it in, and does that leave the ceiling intact — so it is
    # serialized per (person, target) before any of them run. Without this a
    # double tap (which a reaction button invites) can have both requests read
    # "not there yet" and race, and two concurrent adds can each count
    # themselves under the cap.
    #
    # Transaction-scoped, so it releases on commit with no unlock to forget.
    # The key names the person AND the target, so two people reacting to the
    # same comment never wait on each other — only a request racing itself
    # does, which is the only case with anything to serialize.
    await session.exec(
        select(
            func.pg_advisory_xact_lock(func.hashtextextended(_TOGGLE_KEY, 0))
        ).params(toggle_key=f"reaction:{target.value}:{ctx.target_id}:{user.id}")
    )

    mine = (
        Reaction.target_type == target.value,
        Reaction.target_id == ctx.target_id,
        Reaction.created_by == user.id,
    )

    # The DELETE reports whether there was one to take back, so the branch
    # comes from the statement rather than from a read the next statement then
    # trusts.
    removed = (
        (
            await session.exec(
                sa_delete(Reaction)
                .where(*mine, Reaction.emoji == emoji)
                .returning(Reaction.id)
            )
        )
        .scalars()
        .first()
    )
    if removed is not None:
        await withdraw_digest_items(session, reaction_ids=[cast(int, removed)])
        return (
            await summary_for(
                session, target=target, target_id=ctx.target_id, viewer_id=user.id
            ),
            False,
        )

    held = (
        await session.exec(select(func.count()).select_from(Reaction).where(*mine))
    ).one()
    if held >= MAX_REACTIONS_PER_USER:
        raise ReactionValidationError(ReactionMessages.TOO_MANY)

    # ``ON CONFLICT DO NOTHING`` cannot fire while the lock above is held. It
    # stays as the fail-safe: were that lock ever lost, a duplicate degrades to
    # "someone else already added this one" rather than to a 500.
    inserted = (
        (
            await session.exec(
                pg_insert(Reaction)
                .values(
                    target_type=target.value,
                    target_id=ctx.target_id,
                    emoji=emoji,
                    created_by=cast(int, user.id),
                    # Spelled out: this is a Core insert, so the model's
                    # default_factory never runs for it.
                    created_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_nothing(constraint="uq_reactions_target_user_emoji")
                .returning(Reaction.id)
            )
        )
        .scalars()
        .first()
    )
    added = inserted is not None

    if added:
        reaction = (
            await session.exec(select(Reaction).where(Reaction.id == inserted))
        ).one()
        await _queue_reaction_notification(
            session, reaction=reaction, reactor=user, ctx=ctx, guild_id=guild_id
        )

    summary = await summary_for(
        session, target=target, target_id=ctx.target_id, viewer_id=user.id
    )
    return summary, added


async def _queue_reaction_notification(
    session: AsyncSession,
    *,
    reaction: Reaction,
    reactor: User,
    ctx: TargetContext,
    guild_id: int,
) -> None:
    """Tell the author someone reacted — through the digest, never at once.

    A reaction is the lightest signal in the app and they arrive in flurries, so
    the bell gets one entry immediately and email/push wait for the queue to
    settle, exactly as task assignment does.
    """
    from app.services import notifications

    if ctx.author_id is None or ctx.author_id == reactor.id:
        return
    author = (
        await session.exec(select(User).where(User.id == ctx.author_id))
    ).one_or_none()
    if author is None:
        return
    await notifications.enqueue_reaction_event(
        session,
        author=author,
        reactor=reactor,
        reaction=reaction,
        context_title=ctx.title,
        target_path=ctx.target_path,
        guild_id=guild_id,
    )


async def withdraw_digest_items(
    session: AsyncSession, *, reaction_ids: Sequence[int]
) -> None:
    """Drop not-yet-sent digest lines for reactions that no longer exist.

    Un-reacting within the quiet period should leave no trace; a line that has
    already gone out is not chased.
    """
    from app.models.tenant.reaction_digest import ReactionDigestItem

    if not reaction_ids:
        return
    await session.exec(
        sa_delete(ReactionDigestItem).where(
            ReactionDigestItem.reaction_id.in_(tuple(reaction_ids)),
            ReactionDigestItem.processed_at.is_(None),
        )
    )


async def purge_reactions_for(
    session: AsyncSession,
    *,
    target: ReactionTarget,
    target_ids: Sequence[int],
) -> None:
    """Hard-delete every reaction on targets that are being purged.

    Reactions name their target polymorphically, so no foreign key carries them
    out with it — the purge path says so explicitly instead.
    """
    from app.models.tenant.reaction_digest import ReactionDigestItem

    if not target_ids:
        return
    ids = tuple(target_ids)
    await session.exec(
        sa_delete(ReactionDigestItem).where(
            ReactionDigestItem.target_type == target.value,
            ReactionDigestItem.target_id.in_(ids),
        )
    )
    await session.exec(
        sa_delete(Reaction).where(
            Reaction.target_type == target.value,
            Reaction.target_id.in_(ids),
        )
    )


async def purge_comment_reactions(
    session: AsyncSession, comments: Sequence[Comment]
) -> None:
    """The purge hook for comments — called from ``hard_purge_entity``."""
    await purge_reactions_for(
        target=ReactionTarget.comment,
        target_ids=[c.id for c in comments if c.id is not None],
        session=session,
    )
