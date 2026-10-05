"""What the people working an operations case see of how it was filed.

A case is an ordinary task with an ``intake_cases`` row beside it. This reads
that row for the task view: which stream opened it, who filed it and what they
called it, whether the stream holds a conversation with them, and which of the
binding's statuses mean "waiting on them" and "being worked".

Everything is read on the caller's routed session, so a person who cannot read
the task reads nothing here either.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from sqlalchemy.orm import selectinload

from app.core.intake import Conversation, IntakeStream, meta
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.comment import Comment, CommentAudience
from app.models.tenant.intake import IntakeBinding, IntakeCase


@dataclass(frozen=True)
class CaseView:
    stream: IntakeStream
    opened_at: datetime
    filer: Optional[MemberProfile]
    filer_subject: Optional[str]
    #: What the stream allows with whoever filed it; ``none`` where nobody did.
    conversation: Conversation
    awaiting_filer_status_id: Optional[int]
    active_status_id: Optional[int]
    #: The conversation with whoever filed it, oldest first: their words and
    #: what the team said to them. Not part of the task's thread.
    messages: list[Comment]


async def read_case(session: AsyncSession, task_id: int) -> Optional[CaseView]:
    """The case behind ``task_id``, or ``None`` where the task is not one."""
    case = (
        await session.exec(select(IntakeCase).where(IntakeCase.task_id == task_id))
    ).first()
    if case is None:
        return None
    stream = IntakeStream(case.stream)
    binding = (
        await session.exec(
            select(
                IntakeBinding.awaiting_filer_status_id, IntakeBinding.active_status_id
            ).where(IntakeBinding.stream == stream.value)
        )
    ).first()
    filer = None
    if case.filer_user_id is not None:
        filer = (
            await session.exec(
                select(MemberProfile).where(MemberProfile.id == case.filer_user_id)
            )
        ).first()
    return CaseView(
        stream=stream,
        opened_at=case.opened_at,
        filer=filer,
        filer_subject=case.filer_subject,
        conversation=(
            meta(stream).conversation
            if case.filer_user_id is not None
            else Conversation.none
        ),
        awaiting_filer_status_id=binding[0] if binding else None,
        active_status_id=binding[1] if binding else None,
        messages=list(
            (
                await session.exec(
                    select(Comment)
                    .where(Comment.task_id == task_id)
                    .where(Comment.audience == CommentAudience.filer)
                    .options(selectinload(Comment.author))
                    .order_by(Comment.created_at, Comment.id)
                )
            ).all()
        ),
    )
