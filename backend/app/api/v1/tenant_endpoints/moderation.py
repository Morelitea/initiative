"""A community's moderation surface, and the one place a report is sent.

Two audiences, one router:

- **anybody signed in** files a report (``POST /me/reports``). The same call
  from every surface; where it goes is decided server-side.
- **whoever already sees everything in an initiative** reads and settles that
  initiative's reports. Not a role name — the standing is
  ``override_share_restrictions`` ("Full access"), which is what the RLS policy
  on these tables keys on too, so the endpoint and the database agree without
  the endpoint re-deciding.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    UserSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import ModerationMessages
from app.core.moderation import parse_target
from app.models.platform.user import User
from app.schemas.tenant.moderation import (
    ModerationReportList,
    ModerationReportRead,
    ReportAccepted,
    ReportCreate,
    ReportSettle,
)
from app.services.tenant import moderation as moderation_service

router = APIRouter()
me_router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


def _read(report, reporter_count: int, details: list[str]) -> ModerationReportRead:
    return ModerationReportRead(
        id=report.id,
        initiative_id=report.initiative_id,
        target_type=report.target_type,
        target_id=report.target_id,
        reason=report.reason,
        reported_at=report.reported_at,
        reporter_count=reporter_count,
        details=details,
        outcome=report.outcome,
        note=report.note,
        decided_by=report.decided_by,
        decided_at=report.decided_at,
    )


@me_router.post(
    "/reports", response_model=ReportAccepted, status_code=status.HTTP_202_ACCEPTED
)
async def file_report(
    payload: ReportCreate,
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ReportAccepted:
    """Report something. One endpoint, whatever was reported and from where.

    The reply says only that we have it. Whether a report already existed for
    the same thing, who will read it, and what is decided are all none of the
    reporter's business — and saying any of it would leak the moderator's hand.

    The session starts platform-scoped and is routed into the named community
    by the ordinary entry point, so the target is looked up as the reporter and
    a thing they cannot see is a thing they cannot report.
    """
    try:
        target = parse_target(payload.target_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ModerationMessages.UNKNOWN_TARGET_TYPE,
        ) from None

    filed = await moderation_service.file_report(
        session,
        reporter=current_user,
        target=target,
        target_id=payload.target_id,
        reason=payload.reason,
        detail=payload.detail,
        guild_id=payload.guild_id,
    )
    return ReportAccepted(accepted=True, venue=filed.venue)


@router.get("/initiatives/{initiative_id}/reports", response_model=ModerationReportList)
async def list_reports(
    initiative_id: int,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    settled: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ModerationReportList:
    """This initiative's reports.

    No capability check here: the tables carry RLS that admits exactly the
    people who already see everything in the initiative, plus the guild admin.
    A reader who is not one of them gets an empty list, the same way they get
    404 for any content they are not in.
    """
    rows = await moderation_service.list_reports(
        session,
        initiative_id=initiative_id,
        settled=settled,
        limit=limit,
        offset=offset,
    )
    return ModerationReportList(
        items=[_read(report, count, details) for report, count, details in rows],
        total=len(rows),
    )


@router.post("/reports/{report_id}/settle", response_model=ModerationReportRead)
async def settle_report(
    report_id: int,
    payload: ReportSettle,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ModerationReportRead:
    """Settle a report. Every outcome closes it.

    ``escalated`` also opens a platform case carrying the references — the one
    crossing between a community's reports and the operator's, in one direction.
    """
    report = await moderation_service.settle_report(
        session,
        report_id=report_id,
        outcome=payload.outcome,
        note=payload.note,
        decided_by=current_user.id,
    )
    # The same reporter figures the list carries: a settled report is the same
    # shape as an open one, and answering zero would have the page replace what
    # it already had with nothing.
    counts, details = await moderation_service.reporters_for(session, [report.id])
    return _read(report, counts.get(report.id, 0), details.get(report.id, []))
