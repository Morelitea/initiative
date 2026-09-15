"""Filing a report, and settling one.

Where a report goes is not the client's decision. This resolves the target,
derives the venue from the registry the RLS policies are rendered from, and
sends it to one of two places:

- **platform** — an intake case in the operations guild, which is project work
  our own staff triage and assign;
- **initiative** — a row in that community, which its moderators look at and
  decide.

A reporter gains nothing by reporting: the write happens on a routed system
session, and reading the report stays with the people who already see
everything in that initiative.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import IntakeStream
from app.core.messages import ModerationMessages
from app.core.moderation import (
    PlatformReportTarget,
    ReportOutcome,
    ReportReason,
    ReportVenue,
    target_table,
    venue_for,
)
from app.core.search import SearchEntityType
from app.db.session import set_rls_context
from app.models.platform.user import User
from app.models.tenant.moderation import ModerationReport, ModerationReportReporter
from app.services.platform.intake import CaseRefs, open_case

logger = logging.getLogger(__name__)


class ReportFiled:
    """What filing a report did. Deliberately tells the reporter nothing else."""

    __slots__ = ("venue",)

    def __init__(self, venue: ReportVenue) -> None:
        self.venue = venue


async def _resolve_initiative(
    session: AsyncSession, target: SearchEntityType, target_id: int
) -> Optional[tuple[int, int]]:
    """``(guild_id, initiative_id)`` for a community target, or ``None``.

    The initiative is read with the expression
    ``app.db.initiative_rls.INITIATIVE_PATHS`` already declares for that table —
    the same declaration the table's policies are rendered from, so a target's
    venue and its access gate cannot answer differently.

    Runs on a session routed into the guild as admin: placing a report needs to
    reach a row the reporter may not own. It reads **ids only**.
    """
    from app.db.initiative_rls import INITIATIVE_PATHS

    table = target_table(target)
    path = INITIATIVE_PATHS.get(table)
    if path is None:
        return None

    row = (
        await session.exec(
            text(  # noqa: S608 — table and expression come from the registry
                f"SELECT t.guild_id, {path.initiative_expr('t')} AS initiative_id "
                f"FROM {table} t WHERE t.id = :target_id"
            ).bindparams(target_id=target_id)
        )
    ).first()
    if row is None or row.initiative_id is None:
        return None
    return int(row.guild_id), int(row.initiative_id)


async def file_report(
    reporter_session: AsyncSession,
    *,
    reporter: "User",
    target: SearchEntityType | PlatformReportTarget,
    target_id: int,
    reason: ReportReason,
    detail: Optional[str],
    guild_id: Optional[int] = None,
    now: Optional[datetime] = None,
) -> ReportFiled:
    """Route one report to whoever handles that kind of thing.

    ``reporter_session`` is the reporter's own session, and the target is
    resolved **on it** — so a person can only report something they can
    already see, and the database is what decides that rather than a check here.
    ``guild_id`` says which community they were standing in; it is validated as
    theirs before it is used, and it decides nothing about the venue.
    """
    moment = now or datetime.now(timezone.utc)
    venue = venue_for(target)

    if venue is ReportVenue.initiative:
        assert isinstance(target, SearchEntityType)
        located = await _locate_as_reporter(
            reporter_session,
            reporter=reporter,
            target=target,
            target_id=target_id,
            guild_id=guild_id,
        )
        if located is not None:
            await _place_in_initiative(
                guild_id=located[0],
                initiative_id=located[1],
                reporter_id=reporter.id,
                target=target,
                target_id=target_id,
                reason=reason,
                detail=detail,
                moment=moment,
            )
            return ReportFiled(ReportVenue.initiative)
        # The community could not take it — nothing there answers to that id
        # for this reader. The platform is the backstop: a report that resolves
        # nowhere is a report nobody sees.
        logger.info("report on %s:%s fell back to the platform", target, target_id)

    await _open_platform_case(
        target=target,
        target_id=target_id,
        reason=reason,
        detail=detail,
        moment=moment,
    )
    return ReportFiled(ReportVenue.platform)


async def _locate_as_reporter(
    reporter_session: AsyncSession,
    *,
    reporter: "User",
    target: SearchEntityType,
    target_id: int,
    guild_id: Optional[int],
) -> Optional[tuple[int, int]]:
    """``(guild_id, initiative_id)`` for a target this reporter can see.

    Routed as the reporter through the ordinary entry point, so membership,
    the auth policy and every gate apply exactly as they do on a read. A row
    the reporter cannot see resolves to nothing, and so does an id that names
    a different row in a community they merely claimed to be in — ids are
    unique only within a schema.
    """
    if guild_id is None:
        return None
    from app.api.deps import GuildAccessError, establish_guild_access

    try:
        await establish_guild_access(reporter_session, reporter, guild_id)
    except GuildAccessError:
        return None
    return await _resolve_initiative(reporter_session, target, target_id)


async def _place_in_initiative(
    *,
    guild_id: int,
    initiative_id: int,
    reporter_id: int,
    target: SearchEntityType,
    target_id: int,
    reason: ReportReason,
    detail: Optional[str],
    moment: datetime,
) -> None:
    """Open or join the community's report for this target.

    Its own system session, routed as the guild admin: the row belongs to the
    initiative's moderators, and the reporter must not be able to read it back.
    """
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as session:
        await set_rls_context(session, guild_id=guild_id, guild_role="admin")
        existing = (
            await session.exec(
                select(ModerationReport)
                .where(ModerationReport.initiative_id == initiative_id)
                .where(ModerationReport.target_type == target.value)
                .where(ModerationReport.target_id == target_id)
                .where(ModerationReport.outcome.is_(None))
                .execution_options(populate_existing=True)
            )
        ).first()

        if existing is None:
            existing = ModerationReport(
                guild_id=guild_id,
                initiative_id=initiative_id,
                target_type=target.value,
                target_id=target_id,
                reason=reason,
                reported_at=moment,
            )
            session.add(existing)
            await session.flush()

        already = (
            await session.exec(
                select(ModerationReportReporter.id)
                .where(ModerationReportReporter.report_id == existing.id)
                .where(ModerationReportReporter.reporter_id == reporter_id)
            )
        ).first()
        if already is None:
            session.add(
                ModerationReportReporter(
                    report_id=existing.id,
                    reporter_id=reporter_id,
                    reported_at=moment,
                    detail=detail,
                )
            )
        await session.commit()


#: Identity targets whose id names an account. For these the case's subject is
#: the account itself, not the thing it hangs off.
_ACCOUNT_TARGETS = frozenset(
    {
        PlatformReportTarget.user_profile,
        PlatformReportTarget.username,
        PlatformReportTarget.avatar,
        PlatformReportTarget.decoration,
    }
)


async def _open_platform_case(
    *,
    target: SearchEntityType | PlatformReportTarget,
    target_id: int,
    reason: ReportReason,
    detail: Optional[str],
    moment: datetime,
    note: Optional[str] = None,
    reporter_ids: tuple[int, ...] = (),
) -> None:
    """File the report as an intake case in the operations guild.

    ``reporter_ids`` are carried only on an escalation, where judging whether a
    report was made in good faith is the platform's job and the reporters are
    not somebody's neighbours. An ordinary platform report carries none: who
    said it adds nothing to a complaint about a username.
    """
    parts = [part for part in (detail, note) if part]
    if reporter_ids:
        listed = ", ".join(str(i) for i in reporter_ids)
        parts.append(f"Reported by account(s): {listed}")
    await open_case(
        IntakeStream.moderation,
        title=f"Reported {target.value} {target_id} ({reason.value})",
        body="\n\n".join(parts) or None,
        refs=CaseRefs(
            # The subject is who or what was reported — never the reporter.
            subject_user=target_id if target in _ACCOUNT_TARGETS else None,
            resource_type=target.value,
            resource_id=target_id,
            reported_at=moment,
            severity=reason.value,
        ),
        dedupe_key=f"report:{target.value}:{target_id}",
    )


async def settle_report(
    session: AsyncSession,
    *,
    report_id: int,
    outcome: ReportOutcome,
    note: Optional[str],
    decided_by: int,
    now: Optional[datetime] = None,
) -> ModerationReport:
    """Close a community report. Every outcome closes it.

    The session must already be routed into the guild; RLS is what decides
    whether this reader may see the row at all.
    """
    moment = now or datetime.now(timezone.utc)
    report = (
        await session.exec(
            select(ModerationReport)
            .where(ModerationReport.id == report_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if report is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=ModerationMessages.REPORT_NOT_FOUND,
        )
    if report.outcome is not None:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=ModerationMessages.REPORT_ALREADY_SETTLED,
        )

    if outcome is ReportOutcome.escalated:
        # The one crossing between the two shapes, and one direction only.
        reporters = (
            await session.exec(
                select(ModerationReportReporter.reporter_id).where(
                    ModerationReportReporter.report_id == report.id
                )
            )
        ).all()
        await _open_platform_case(
            target=SearchEntityType(report.target_type),
            target_id=report.target_id,
            reason=ReportReason(report.reason),
            detail=None,
            moment=moment,
            note=note,
            reporter_ids=tuple(reporters),
        )

    report.outcome = outcome
    report.note = note
    report.decided_by = decided_by
    report.decided_at = moment
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return report


async def list_reports(
    session: AsyncSession,
    *,
    initiative_id: int,
    settled: bool = False,
) -> list[tuple[ModerationReport, int, list[str]]]:
    """Reports for one initiative, with how many people reported each.

    The session must already be routed; RLS decides whether this reader sees
    any of it. Reporter **identities** are deliberately not returned — the
    count is what a moderator needs, and the words come unattributed.
    """
    stmt = select(ModerationReport).where(
        ModerationReport.initiative_id == initiative_id
    )
    stmt = (
        stmt.where(ModerationReport.outcome.is_not(None))
        if settled
        else stmt.where(ModerationReport.outcome.is_(None))
    )
    reports = (
        await session.exec(
            stmt.order_by(ModerationReport.reported_at.desc()).execution_options(
                populate_existing=True
            )
        )
    ).all()
    if not reports:
        return []

    rows = (
        await session.exec(
            select(
                ModerationReportReporter.report_id,
                ModerationReportReporter.detail,
            ).where(ModerationReportReporter.report_id.in_([r.id for r in reports]))
        )
    ).all()
    by_report: dict[int, list[str]] = {}
    counts: dict[int, int] = {}
    for report_id, detail in rows:
        counts[report_id] = counts.get(report_id, 0) + 1
        if detail:
            by_report.setdefault(report_id, []).append(detail)
    return [
        (report, counts.get(report.id, 0), by_report.get(report.id, []))
        for report in reports
    ]
