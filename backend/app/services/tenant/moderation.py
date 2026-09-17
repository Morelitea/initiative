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
from sqlalchemy import Table, select as sa_select, text, tuple_
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import IntakeStream
from app.core.messages import ModerationMessages
from app.core.moderation import (
    PLATFORM_TARGET_RELATION,
    PlatformReportTarget,
    ReportOutcome,
    ReportReason,
    ReportVenue,
    target_table,
    venue_for,
)
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.db.session import set_rls_context
from app.models.platform import user_profile_view
from app.models.platform.user import User
from app.models.tenant.moderation import ModerationReport, ModerationReportReporter
from app.models.tenant.search_entry import SearchEntry
from app.services.platform.intake import CaseRefs, open_case
from app.services.tenant.search import search_scope_clause

logger = logging.getLogger(__name__)


class ReportFiled:
    """What filing a report did. Deliberately tells the reporter nothing else."""

    __slots__ = ("venue",)

    def __init__(self, venue: ReportVenue) -> None:
        self.venue = venue


def public_relation(name: str) -> Table:
    """The table object for a relation ``PLATFORM_TARGET_RELATION`` names.

    Two registries are asked in turn because ``user_profiles`` is a view, and a
    view deliberately keeps its own metadata rather than sitting among the
    models. Asking both is what keeps this from being a second list saying
    which relation is which. ``moderation_test`` resolves every entry, so a
    target added later cannot name a relation that is not there.
    """
    view = user_profile_view.metadata.tables.get(f"public.{name}")
    return view if view is not None else SQLModel.metadata.tables[name]


async def _resolve_initiative(
    session: AsyncSession, target: SearchEntityType, target_id: int
) -> Optional[tuple[int, int]]:
    """``(guild_id, initiative_id)`` for a community target, or ``None``.

    The initiative is read with the expression
    ``app.db.initiative_rls.INITIATIVE_PATHS`` already declares for that table —
    the same declaration the table's policies are rendered from, so a target's
    venue and its access gate cannot answer differently.

    Runs on the reporter's own session, so what they can see decides what
    resolves. It reads **ids only**.

    The query is built from the table's own column objects and one bound id —
    the shape ``app.db.reference_targets`` already uses to ask the registry the
    same question — so the only text in it is the registry's own expression.
    """
    from app.db.initiative_rls import INITIATIVE_PATHS

    table_name = target_table(target)
    path = INITIATIVE_PATHS.get(table_name)
    relation = SQLModel.metadata.tables.get(table_name)
    if path is None or relation is None or "guild_id" not in relation.c:
        return None

    row = (
        await session.exec(
            sa_select(
                relation.c["guild_id"],
                text(path.initiative_expr(table_name)),
            ).where(relation.c["id"] == target_id)
        )
    ).first()
    if row is None or row[1] is None:
        return None
    return int(row[0]), int(row[1])


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

    if isinstance(target, PlatformReportTarget) and not await _platform_target_visible(
        reporter_session, target, target_id
    ):
        # Checked before it becomes somebody's work, so no operations task
        # names something the reporter could not see. Refused the same way
        # whether the row is hidden from them or not there at all.
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=ModerationMessages.TARGET_NOT_FOUND,
        )

    opened = await _open_platform_case(
        target=target,
        target_id=target_id,
        reason=reason,
        detail=detail,
        moment=moment,
    )
    if not opened:
        # Nothing is bound to receive it. Say so rather than answering 202 to
        # a report that reached nobody.
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ModerationMessages.NOWHERE_TO_SEND,
        )
    return ReportFiled(ReportVenue.platform)


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
        # Two people reporting the same thing in the same instant both look for
        # an open row before either writes one. They queue here instead, so the
        # second joins the first rather than losing the unique index. Held for
        # the rest of the transaction; the guild id is one half of the key
        # because advisory locks are cluster-wide where a schema is per-guild.
        await session.exec(
            text("SELECT pg_advisory_xact_lock(:guild, hashtext(:key))").bindparams(
                guild=guild_id, key=f"{initiative_id}:{target.value}:{target_id}"
            )
        )
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


async def _platform_target_visible(
    reporter_session: AsyncSession,
    target: PlatformReportTarget,
    target_id: int,
) -> bool:
    """Whether this reporter can see the platform target they named.

    Asked on their own session, against the relation that already serves the
    thing publicly (``PLATFORM_TARGET_RELATION``) — so a row they may not see
    and a row that is not there answer identically, and reporting reaches
    exactly as far as looking does. The community half works the same way.
    """
    relation = public_relation(PLATFORM_TARGET_RELATION[target])
    stmt = sa_select(relation.c["id"]).where(relation.c["id"] == target_id)
    if target is PlatformReportTarget.directory_listing:
        stmt = stmt.where(relation.c["is_community"].is_(True))
    return (await reporter_session.exec(stmt)).first() is not None


async def _open_platform_case(
    *,
    target: SearchEntityType | PlatformReportTarget,
    target_id: int,
    reason: ReportReason,
    detail: Optional[str],
    moment: datetime,
    note: Optional[str] = None,
    reporter_ids: tuple[int, ...] = (),
) -> bool:
    """File the report as an intake case in the operations guild.

    Returns whether a case actually opened. ``open_case`` answers ``None`` on
    a deployment that has bound no moderation project — which is every fresh
    install — and a report that opened nothing has not been received.

    ``reporter_ids`` are carried only on an escalation, where judging whether a
    report was made in good faith is the platform's job and the reporters are
    not somebody's neighbours. An ordinary platform report carries none: who
    said it adds nothing to a complaint about a username.
    """
    parts = [part for part in (detail, note) if part]
    if reporter_ids:
        listed = ", ".join(str(i) for i in reporter_ids)
        parts.append(f"Reported by account(s): {listed}")
    outcome = await open_case(
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
    return outcome is not None


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
    # Locked before it is read, so two moderators deciding at once resolve in
    # order: the second finds it settled rather than overwriting the first's
    # outcome, note and name.
    report = (
        await session.exec(
            select(ModerationReport)
            .where(ModerationReport.id == report_id)
            .with_for_update()
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
        #
        # The case is opened before the report closes, and on its own
        # transaction. If closing then fails, the report stays open and a
        # moderator escalates again — which opens no second case, because the
        # writer keys on the target and joins the one already open. The other
        # order would risk a closed report whose escalation never left.
        reporters = (
            await session.exec(
                select(ModerationReportReporter.reporter_id).where(
                    ModerationReportReporter.report_id == report.id
                )
            )
        ).all()
        opened = await _open_platform_case(
            target=SearchEntityType(report.target_type),
            target_id=report.target_id,
            reason=ReportReason(report.reason),
            detail=None,
            moment=moment,
            note=note,
            reporter_ids=tuple(reporters),
        )
        if not opened:
            # Nothing is bound to receive it, so the report stays open and the
            # moderator is told. Closing it as escalated would record a handover
            # that never happened.
            raise HTTPException(
                status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=ModerationMessages.NOWHERE_TO_SEND,
            )

    report.outcome = outcome
    report.note = note
    report.decided_by = decided_by
    report.decided_at = moment
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return report


async def reporters_for(
    session: AsyncSession, report_ids: list[int]
) -> tuple[dict[int, int], dict[int, list[str]]]:
    """How many people reported each, and what they said — never who."""
    if not report_ids:
        return {}, {}
    rows = (
        await session.exec(
            select(
                ModerationReportReporter.report_id,
                ModerationReportReporter.detail,
            ).where(ModerationReportReporter.report_id.in_(report_ids))
        )
    ).all()
    counts: dict[int, int] = {}
    details: dict[int, list[str]] = {}
    for report_id, detail in rows:
        counts[report_id] = counts.get(report_id, 0) + 1
        if detail:
            details.setdefault(report_id, []).append(detail)
    return counts, details


#: The entity type a comment's parent column names. Every declared parent is a
#: kind in its own right, so the column's own name is the answer and there is no
#: second list to keep in step.
def _parent_entity(column: str) -> SearchEntityType:
    return SearchEntityType(column.removesuffix("_id"))


class TargetLocation:
    """What to open to go and read a reported thing.

    The target itself for everything with a page of its own, and the thing a
    comment was said on for a comment — a comment is read where it was written,
    and its own id addresses nothing. ``tool`` is what it is addressed inside,
    since a task needs its project's id to be addressed at all.
    """

    __slots__ = ("entity_type", "entity_id", "tool", "tool_id")

    def __init__(
        self, entity_type: str, entity_id: int, tool: Tool, tool_id: int
    ) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.tool = tool
        self.tool_id = tool_id


class TargetPreview:
    """A line of a reported thing, and where to go and read it.

    Either half can be absent on its own: a comment whose parent this reader
    cannot reach still shows what it said, and a thing whose own index entry has
    gone can still be opened.
    """

    __slots__ = ("excerpt", "location")

    def __init__(
        self, excerpt: Optional[str], location: Optional[TargetLocation]
    ) -> None:
        self.excerpt = excerpt
        self.location = location


async def _comment_parents(
    session: AsyncSession, comment_ids: list[int]
) -> dict[int, tuple[str, int]]:
    """What each of these comments was said on — the kind, and which one.

    Read from the comment's own parent columns, declared once in
    ``COMMENT_PARENT_COLUMNS``, rather than from the index's sharing pair: the
    two differ for the one parent whose sharing is not its own — a comment on a
    task is shared as part of the task's *project*, and read on the task.
    """
    from app.db.initiative_rls import COMMENT_PARENT_COLUMNS

    if not comment_ids:
        return {}

    comments = SQLModel.metadata.tables["comments"]
    columns = [comments.c[name] for name in COMMENT_PARENT_COLUMNS]
    rows = (
        await session.exec(
            sa_select(comments.c["id"], *columns).where(
                comments.c["id"].in_(comment_ids)
            )
        )
    ).all()

    parents: dict[int, tuple[str, int]] = {}
    for row in rows:
        for name, value in zip(COMMENT_PARENT_COLUMNS, row[1:]):
            if value is not None:
                # Exactly one is set — the table's own check constraint says so.
                parents[row[0]] = (_parent_entity(name).value, int(value))
                break
    return parents


async def target_previews(
    session: AsyncSession,
    reports: list[ModerationReport],
    *,
    user_id: int,
    guild_id: int,
) -> dict[int, TargetPreview]:
    """A line of each report's target, and what to open to reach it.

    Read from ``search_entries`` rather than from each kind's own table: the
    index already holds, per row, the one line that stands for it — a comment's
    opening, everything else's name — and the tool it is addressed inside,
    which is what a link to a thing with no page of its own is built from. So
    every reportable kind is covered here without a switch over kinds, and a
    kind added later arrives with one.

    Narrowed by ``search_scope_clause``, the same ``public.resource_access``
    call the table's own policies make. A moderator's standing already clears
    it for their initiative; a target they cannot reach comes back absent, and
    so does one that has since been deleted — the index drops with the row.
    """
    if not reports:
        return {}

    # A comment is read on the thing it was said on, so that is what a link to
    # it opens. Everything else answers for itself.
    parents = await _comment_parents(
        session,
        [r.target_id for r in reports if r.target_type == SearchEntityType.comment],
    )
    destination = {
        (r.target_type, r.target_id): (
            parents.get(r.target_id)
            if r.target_type == SearchEntityType.comment
            else (r.target_type, r.target_id)
        )
        for r in reports
    }

    pairs = set(destination) | {d for d in destination.values() if d is not None}
    rows = (
        await session.exec(
            select(
                SearchEntry.entity_type,
                SearchEntry.entity_id,
                SearchEntry.title,
                SearchEntry.dac_tool,
                SearchEntry.dac_id,
            )
            .where(
                tuple_(SearchEntry.entity_type, SearchEntry.entity_id).in_(
                    sorted(pairs)
                )
            )
            # The first chunk. Long text is split across rows, and the title is
            # the same on each of them.
            .where(SearchEntry.chunk_ix == 0)
            .where(search_scope_clause(user_id, guild_id=guild_id))
        )
    ).all()
    found = {(row[0], row[1]): row for row in rows}

    previews: dict[int, TargetPreview] = {}
    for report in reports:
        target = found.get((report.target_type, report.target_id))
        reached = destination[(report.target_type, report.target_id)]
        # Reachable is the index's answer for BOTH: a moderator who cannot see
        # what a comment was said on is not sent to it, whatever they can see
        # of the comment itself.
        where = found.get(reached) if reached is not None else None
        location = (
            TargetLocation(where[0], where[1], Tool(where[3]), where[4])
            # A kind carrying no tool at all — the guild's own vocabulary — is
            # not something a community report can name, and is not addressed
            # from here if one ever does.
            if where is not None and where[3] and where[4] is not None
            else None
        )
        if target is None and location is None:
            continue
        previews[report.id] = TargetPreview(
            excerpt=target[2] if target is not None else None,
            location=location,
        )
    return previews


async def list_reports(
    session: AsyncSession,
    *,
    initiative_id: int,
    settled: bool = False,
    limit: int = 50,
    offset: int = 0,
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
            # A second key, because two reports can share a timestamp and an
            # offset page needs one order to be paged through.
            stmt.order_by(
                ModerationReport.reported_at.desc(), ModerationReport.id.desc()
            )
            .offset(offset)
            .limit(limit)
            .execution_options(populate_existing=True)
        )
    ).all()
    if not reports:
        return []

    counts, details = await reporters_for(session, [r.id for r in reports])
    return [
        (report, counts.get(report.id, 0), details.get(report.id, []))
        for report in reports
    ]
