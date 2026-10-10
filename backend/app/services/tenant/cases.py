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

from app.core.intake import Conversation, IntakeStream, conversation_for
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.comment import Comment, CommentAudience
from app.models.tenant.evidence import Evidence
from app.models.tenant.intake import IntakeBinding, IntakeCase


@dataclass(frozen=True)
class CaseView:
    stream: IntakeStream
    opened_at: datetime
    filer: Optional[MemberProfile]
    filer_subject: Optional[str]
    #: What the case allows with whoever filed it; ``none`` where nobody did.
    conversation: Conversation
    awaiting_filer_status_id: Optional[int]
    active_status_id: Optional[int]
    #: The conversation with whoever filed it, oldest first: their words and
    #: what the team said to them. Not part of the task's thread.
    messages: list[Comment]
    #: What was attached to it, oldest first.
    evidence: list[Evidence]
    #: What it is about, as its references recorded it: the community, and
    #: the kind and id of the thing in it. ``None`` where they say nothing.
    subject_guild_id: Optional[int] = None
    resource_type: Optional[str] = None
    resource_id: Optional[int] = None
    #: What it is about within its stream, as its filer chose.
    topic: Optional[str] = None


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
    from app.services.platform import evidence as evidence_service

    attached = await evidence_service.listed(session, case_ids=[int(case.id)])
    return CaseView(
        stream=stream,
        opened_at=case.opened_at,
        filer=filer,
        filer_subject=case.filer_subject,
        conversation=(
            conversation_for(stream, case.topic)
            if case.filer_user_id is not None
            else Conversation.none
        ),
        topic=case.topic,
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
        evidence=attached.get(("case", int(case.id)), []),
        **await _subject(session, task_id),
    )


async def _subject(session: AsyncSession, task_id: int) -> dict[str, object]:
    """The case's subject, from the references it was opened with: the task's
    values for the case fields that name it."""
    from app.core.intake import CaseField
    from app.services.tenant.properties import summaries_by_id

    values = {
        summary.name: summary.value
        for summary in (await summaries_by_id(session, "task", [task_id])).get(
            task_id, []
        )
    }

    def whole(name: str) -> Optional[int]:
        value = values.get(name)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    kind = values.get(CaseField.resource_type.value)
    return {
        "subject_guild_id": whole(CaseField.subject_guild.value),
        "resource_type": str(kind) if kind else None,
        "resource_id": whole(CaseField.resource_id.value),
    }
