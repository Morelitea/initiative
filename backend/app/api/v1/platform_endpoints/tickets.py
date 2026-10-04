"""Filing a ticket: help, a report, and later the other kinds.

Two routes, both the signed-in person's own:

- ``GET /me/tickets/availability`` — what every stream offers them from where
  they are standing: a form, the stream's contact address, or nothing.
- ``POST /me/tickets`` — the filing itself. The body names its stream, and the
  stream decides what it means.

And the cases they filed, which they follow: the list, one case with what has
been said to them about it, and their answer. What a filer reads is decided by
the operations community's filer role (``app.db.filer_access``), which these
routes read through.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from app.api.deps import UserSessionDep, get_current_active_user
from app.core.intake import IntakeStream
from app.core.messages import (
    ModerationMessages,
    SupportMessages,
    TicketMessages,
)
from app.core.moderation import parse_target
from app.models.platform.user import User
from app.schemas.platform.ticket import (
    FiledTicketDetailRead,
    FiledTicketList,
    FiledTicketRead,
    ModerationTicketCreate,
    StreamAvailabilityRead,
    SupportTicketCreate,
    TicketAccepted,
    TicketAvailability,
    TicketCreate,
    TicketMessageRead,
    TicketReplyCreate,
)
from app.services.platform import tickets as tickets_service
from app.services.platform.intake import CaseCapReached
from app.services.tenant import moderation as moderation_service
from app.services.tenant import support as support_service

me_router = APIRouter(prefix="/tickets")

CurrentUser = Annotated[User, Depends(get_current_active_user)]


@me_router.get("/availability", response_model=TicketAvailability)
async def read_ticket_availability(
    session: UserSessionDep,
    current_user: CurrentUser,
    guild_id: Optional[int] = Query(
        default=None,
        description="The community the reader is standing in.",
        alias="community_id",
    ),
) -> TicketAvailability:
    """What each kind of ticket offers the reader from where they are.

    A form where there is somewhere to send it and they may; otherwise the
    kind's contact address; otherwise nothing. Asked by every surface that
    files one, so none of them decides it.
    """
    offered = await tickets_service.availability(
        session, user=current_user, guild_id=guild_id
    )
    return TicketAvailability(
        **{
            stream.value: StreamAvailabilityRead(
                mode=answer.mode, contact=answer.contact
            )
            for stream, answer in offered.items()
        }
    )


@me_router.post("", response_model=TicketAccepted, status_code=status.HTTP_202_ACCEPTED)
async def file_ticket(
    session: UserSessionDep,
    current_user: CurrentUser,
    payload: Annotated[TicketCreate, Body()],
) -> TicketAccepted:
    """File a ticket. One route, whatever kind and from wherever.

    The reply says that it arrived and nothing more: not who will read it, and
    for a report not whether one already existed.
    """
    stream = IntakeStream(payload.stream)
    try:
        await tickets_service.hold_pace(current_user, stream)
    except tickets_service.FilingTooFast as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=TicketMessages.FILING_TOO_FAST,
        ) from exc

    if isinstance(payload, SupportTicketCreate):
        return await _ask_for_help(current_user, payload)
    return await _report(session, current_user, payload)


async def _ask_for_help(
    requester: User, payload: SupportTicketCreate
) -> TicketAccepted:
    try:
        await support_service.request_help(
            guild_id=payload.community_id,
            requester=requester,
            subject=payload.subject,
            body=payload.body,
        )
    except support_service.SupportUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=SupportMessages.NOT_AVAILABLE,
        ) from exc
    except CaseCapReached as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=TicketMessages.TOO_MANY_OPEN,
        ) from exc
    except support_service.NowhereToSend as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=SupportMessages.NOWHERE_TO_SEND,
        ) from exc
    return TicketAccepted()


async def _report(
    session: UserSessionDep, reporter: User, payload: ModerationTicketCreate
) -> TicketAccepted:
    try:
        target = parse_target(payload.target_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ModerationMessages.UNKNOWN_TARGET_TYPE,
        ) from None

    filed = await moderation_service.file_report(
        session,
        reporter=reporter,
        target=target,
        target_id=payload.target_id,
        reason=payload.reason,
        detail=payload.detail,
        guild_id=payload.community_id,
    )
    return TicketAccepted(venue=filed.venue)


def _filed(ticket: tickets_service.FiledTicket) -> FiledTicketRead:
    return FiledTicketRead(
        task_id=ticket.task_id,
        stream=ticket.stream,
        subject=ticket.subject,
        state=ticket.state,
        opened_at=ticket.opened_at,
        updated_at=ticket.updated_at,
    )


@me_router.get("", response_model=FiledTicketList)
async def list_filed_tickets(current_user: CurrentUser) -> FiledTicketList:
    """The cases the reader filed, most recently moved first."""
    filed = await tickets_service.list_filed(current_user)
    return FiledTicketList(items=[_filed(ticket) for ticket in filed])


@me_router.get("/{task_id}", response_model=FiledTicketDetailRead)
async def read_filed_ticket(
    task_id: int, current_user: CurrentUser
) -> FiledTicketDetailRead:
    """One case the reader filed, with what has been said to them about it.

    A case that is not theirs answers exactly as one that does not exist.
    """
    try:
        detail = await tickets_service.read_filed(current_user, task_id)
    except tickets_service.TicketNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=TicketMessages.NOT_FOUND,
        ) from exc
    return FiledTicketDetailRead(
        **_filed(detail.ticket).model_dump(),
        conversation=detail.conversation,
        can_reply=detail.can_reply,
        messages=[
            TicketMessageRead(
                id=message.id,
                mine=message.mine,
                content=message.content,
                created_at=message.created_at,
            )
            for message in detail.messages
        ],
    )


@me_router.post(
    "/{task_id}/replies",
    response_model=FiledTicketDetailRead,
    status_code=status.HTTP_201_CREATED,
)
async def reply_to_filed_ticket(
    task_id: int,
    payload: TicketReplyCreate,
    current_user: CurrentUser,
) -> FiledTicketDetailRead:
    """Answer on a case the reader filed. Returns the case as it now stands.

    Paced like a filing into the case's stream: each answer is something a
    person reads.
    """
    try:
        detail = await tickets_service.read_filed(current_user, task_id)
        await tickets_service.hold_pace(current_user, detail.ticket.stream)
        await tickets_service.reply(current_user, detail, payload.body)
    except tickets_service.TicketNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=TicketMessages.NOT_FOUND,
        ) from exc
    except tickets_service.FilingTooFast as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=TicketMessages.FILING_TOO_FAST,
        ) from exc
    except tickets_service.ReplyRefused as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=TicketMessages.REPLY_NOT_TAKEN,
        ) from exc
    return await read_filed_ticket(task_id, current_user)
