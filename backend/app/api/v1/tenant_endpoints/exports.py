"""Export endpoints: create (auto inline-vs-job), poll, and download.

The artifact is content, so its download is a gated read: the download route
loads the ExportJob row under RLS (own-row + guild-admin policies) — that
lookup IS the authorization — and only then streams the file from the guild's
storage backend. Artifacts are deliberately never registered in ``uploads``,
so the guild-wide ``/uploads/{guild_id}/…`` media route cannot serve them: an
export is a per-user snapshot and may contain initiative-isolated content the
rest of the guild must not reach.
"""

import json
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Annotated, Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlmodel import select

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.messages import ExportMessages
from app.core.user_display import display_name
from app.models.platform.user import User
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.export_job import ExportJob, ExportJobStatus
from app.schemas.tenant.backup_export import BackupEstimate
from app.schemas.tenant.export_job import ExportJobRead, GuildExportStatus
from app.services import audit as audit_service
from app.services.export.engine import ExportError, InlineExport, start_export
from app.services.storage import (
    build_upload_response,
    content_disposition_attachment,
    get_guild_storage,
)

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]

_LIST_LIMIT = 50


def _inline_response(result: InlineExport) -> Response:
    # The filename can carry user text (document titles, original upload
    # names) — the helper escapes it (RFC 5987) so it can't break the header.
    return Response(
        content=result.content,
        media_type=result.content_type,
        headers={
            "Content-Disposition": content_disposition_attachment(result.filename)
        },
    )


def _allow_job(guild_context: GuildContext) -> bool:
    """Enqueueing a job authors a row. A guild in read_only lifecycle can't
    write, and neither can a grantee: a grant reaches existing content. Inline
    export stays available to all — it is a formatted read."""
    if guild_context.content_read_only:
        return False
    if guild_context.is_pam:
        return False
    return True


def _job_response(
    job: ExportJob, status_code: int = status.HTTP_200_OK
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ExportJobRead.model_validate(job).model_dump(mode="json"),
    )


@router.get("/tasks", response_model=None)
async def export_tasks(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    # Literal so the HTTP layer 422s garbage and OpenAPI carries the enum;
    # grows as formats land. The registry still guards per-source combos.
    format: Literal["pdf", "csv", "xlsx", "md"] = Query(default="pdf"),
    conditions: Optional[str] = Query(
        default=None, description="Same JSON filter conditions as the task list"
    ),
    sorting: Optional[str] = Query(
        default=None, description="Same JSON sort fields as the task list"
    ),
    tz: Optional[str] = Query(default=None, description="IANA timezone name"),
    include_archived: bool = Query(default=False),
    layout: Literal["table", "checklist", "detailed"] = Query(
        default="table",
        description=(
            "Report layout. Markdown: a table (default) or a GitHub-style task "
            "list (checklist). PDF: the default table, or 'detailed' for a "
            "one-task-per-page report with description, checklist and comments. "
            "Ignored by csv/xlsx."
        ),
    ),
) -> Union[Response, JSONResponse]:
    """Export the task list (the same visibility and filters as ``GET
    /tasks/``) as a formatted document. Small results render inline and return
    the file directly; large results return ``202`` with a queued job to poll
    and download."""
    try:
        result = await start_export(
            session,
            user=current_user,
            guild_id=guild_context.guild_id,
            source="tasks",
            format=format,
            params={
                "conditions": conditions,
                "sorting": sorting,
                "tz": tz,
                "include_archived": include_archived,
                "layout": layout,
            },
            allow_job=_allow_job(guild_context),
        )
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code)

    if isinstance(result, InlineExport):
        return _inline_response(result)
    return _job_response(result, status_code=status.HTTP_202_ACCEPTED)


@router.get("/project", response_model=None)
async def export_project(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    project_id: Optional[int] = Query(default=None),
    project_ids: Optional[list[int]] = Query(
        default=None, description="Bulk selection: one artifact per project, zipped"
    ),
    format: Literal["json", "pdf", "csv", "xlsx"] = Query(default="json"),
    tz: Optional[str] = Query(
        default=None, max_length=64, description="IANA timezone for report timestamps"
    ),
) -> Union[Response, JSONResponse]:
    """Export a project: ``json`` is the self-contained backup envelope (the
    same JSON ``POST /projects/import`` consumes); ``pdf``/``csv``/``xlsx``
    render a project report (unarchived tasks). Requires write access on the
    project. Small projects return the file inline; large ones return ``202``
    with a queued job to poll and download."""
    try:
        result = await start_export(
            session,
            user=current_user,
            guild_id=guild_context.guild_id,
            source="project",
            format=format,
            params={
                "project_id": project_id,
                "project_ids": project_ids,
                "tz": tz,
            },
            allow_job=_allow_job(guild_context),
        )
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code)

    if isinstance(result, InlineExport):
        return _inline_response(result)
    return _job_response(result, status_code=status.HTTP_202_ACCEPTED)


@router.get("/document", response_model=None)
async def export_document(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    document_id: Optional[int] = Query(default=None),
    document_ids: Optional[list[int]] = Query(
        default=None,
        description=(
            "Bulk selection: one artifact per document, zipped. The format "
            "must be valid for every selected document's type."
        ),
    ),
    format: Literal["json", "md", "csv", "xlsx", "file", "pdf", "docx"] = Query(),
    tz: Optional[str] = Query(
        default=None, max_length=64, description="IANA timezone for report timestamps"
    ),
) -> Union[Response, JSONResponse]:
    """Export a document. Valid formats depend on the document type:
    ``json`` for Lexical (importable envelope) and whiteboards (standard
    Excalidraw file), ``csv``/``xlsx`` for spreadsheets, ``file`` for uploaded
    files (unconverted, original name), ``md`` for smart links. Read access
    suffices. Small documents return the file inline; large ones return
    ``202`` with a queued job to poll and download."""
    try:
        result = await start_export(
            session,
            user=current_user,
            guild_id=guild_context.guild_id,
            source="document",
            format=format,
            params={
                "document_id": document_id,
                "document_ids": document_ids,
                "tz": tz,
            },
            allow_job=_allow_job(guild_context),
        )
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code)

    if isinstance(result, InlineExport):
        return _inline_response(result)
    return _job_response(result, status_code=status.HTTP_202_ACCEPTED)


@router.get("/queue", response_model=None)
async def export_queue(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    queue_id: Optional[int] = Query(default=None),
    queue_ids: Optional[list[int]] = Query(
        default=None, description="Bulk selection: one artifact per queue, zipped"
    ),
    format: Literal["json", "pdf", "csv", "xlsx", "md"] = Query(default="json"),
    tz: Optional[str] = Query(
        default=None, max_length=64, description="IANA timezone for report timestamps"
    ),
) -> Union[Response, JSONResponse]:
    """Export a queue: ``json`` is an importable envelope (items, rotation
    state, tags by name — member assignments and linked documents/tasks ride
    along as display text); ``pdf``/``csv``/``xlsx`` render the turn order as
    a table and ``md`` as a numbered list. Read access suffices.
    Small queues return the file inline; large ones return ``202`` with a
    queued job to poll and download."""
    try:
        result = await start_export(
            session,
            user=current_user,
            guild_id=guild_context.guild_id,
            source="queue",
            format=format,
            params={"queue_id": queue_id, "queue_ids": queue_ids, "tz": tz},
            allow_job=_allow_job(guild_context),
        )
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code)

    if isinstance(result, InlineExport):
        return _inline_response(result)
    return _job_response(result, status_code=status.HTTP_202_ACCEPTED)


@router.get("/counter-group", response_model=None)
async def export_counter_group(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    counter_group_id: Optional[int] = Query(default=None),
    counter_group_ids: Optional[list[int]] = Query(
        default=None, description="Bulk selection: one artifact per group, zipped"
    ),
    format: Literal["json", "pdf", "csv", "xlsx", "md"] = Query(default="json"),
    tz: Optional[str] = Query(
        default=None, max_length=64, description="IANA timezone for report timestamps"
    ),
) -> Union[Response, JSONResponse]:
    """Export a counter group: ``json`` is an importable envelope (every
    counter's configuration and current value); ``pdf``/``csv``/``xlsx``/
    ``md`` render the counters as a table. Read access suffices. Small groups
    return the file inline; large ones return ``202`` with a queued job to
    poll and download."""
    try:
        result = await start_export(
            session,
            user=current_user,
            guild_id=guild_context.guild_id,
            source="counter-group",
            format=format,
            params={
                "counter_group_id": counter_group_id,
                "counter_group_ids": counter_group_ids,
                "tz": tz,
            },
            allow_job=_allow_job(guild_context),
        )
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code)

    if isinstance(result, InlineExport):
        return _inline_response(result)
    return _job_response(result, status_code=status.HTTP_202_ACCEPTED)


@router.get("/dashboard", response_model=None)
async def export_dashboard(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    dashboard_id: Optional[int] = Query(default=None),
    dashboard_ids: Optional[list[int]] = Query(
        default=None, description="Bulk selection: one artifact per dashboard, zipped"
    ),
    format: Literal["json"] = Query(default="json"),
    tz: Optional[str] = Query(
        default=None, max_length=64, description="IANA timezone for report timestamps"
    ),
) -> Union[Response, JSONResponse]:
    """Export a dashboard as an importable envelope: its presentation spec and
    canvas config. A dashboard owns no child content — the data it displays
    belongs to the tools it points at — so there is no report format. Read
    access suffices. A dashboard built on an app this build does not ship
    cannot be exported; install that app where you want it instead. Small
    selections return the file inline; large ones return ``202`` with a queued
    job to poll and download."""
    try:
        result = await start_export(
            session,
            user=current_user,
            guild_id=guild_context.guild_id,
            source="dashboard",
            format=format,
            params={
                "dashboard_id": dashboard_id,
                "dashboard_ids": dashboard_ids,
                "tz": tz,
            },
            allow_job=_allow_job(guild_context),
        )
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code)

    if isinstance(result, InlineExport):
        return _inline_response(result)
    return _job_response(result, status_code=status.HTTP_202_ACCEPTED)


@router.get("/calendar", response_model=None)
async def export_calendars(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    calendar_id: Optional[int] = Query(default=None),
    calendar_ids: Optional[list[int]] = Query(
        default=None, description="Bulk selection of calendars"
    ),
    initiative_id: Optional[int] = Query(
        default=None,
        description=(
            "All exportable calendars in this initiative (ignored when ids given)"
        ),
    ),
    format: Literal["ics", "json"] = Query(default="ics"),
    tz: Optional[str] = Query(
        default=None, max_length=64, description="IANA timezone for report timestamps"
    ),
) -> Union[Response, JSONResponse]:
    """Export calendars: ``ics`` is one iCalendar file per calendar (RRULE and
    attendee RSVPs preserved); ``json`` is one importable envelope per
    calendar holding its events. With no ids and no initiative, every calendar
    visible to the caller in the guild exports — calendar sharing applies
    throughout. Read access suffices. Small exports return the file inline;
    large ones return ``202`` with a queued job to poll and download."""
    try:
        result = await start_export(
            session,
            user=current_user,
            guild_id=guild_context.guild_id,
            source="calendar",
            format=format,
            params={
                "calendar_id": calendar_id,
                "calendar_ids": calendar_ids,
                "initiative_id": initiative_id,
                "tz": tz,
            },
            allow_job=_allow_job(guild_context),
        )
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code)

    if isinstance(result, InlineExport):
        return _inline_response(result)
    return _job_response(result, status_code=status.HTTP_202_ACCEPTED)


def _parse_json_param(raw: Optional[str]) -> Optional[dict]:
    """`include`/`formats` arrive as JSON-string query params (the same
    convention as the task list's `conditions`). Shape validation happens in
    the adapter at count time; here we only reject non-JSON/non-object."""
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ExportMessages.EXPORT_INVALID_PARAMS,
        )
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ExportMessages.EXPORT_INVALID_PARAMS,
        )
    return value


def _require_guild_seat(guild_context: GuildContext) -> None:
    """A whole community's archive belongs to the seat.

    The community's every initiative in one file is not the same errand as
    running the community, so it sits with the seat rather than with an
    ordinary admin — beside the other things only that seat decides.

    Lent as well as held: a ``superadmin`` settings grant is the seat for its
    window, and taking the community out is one of the things that seat does.
    Content access is a separate axis, and this route reads content — a grant
    carrying none is refused at the session, before this.
    """

    if not guild_context.seat:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ExportMessages.EXPORT_SUPERADMIN_REQUIRED,
        )


async def _guild_export_available_at(session) -> Optional[datetime]:
    """When the next whole-community export may start — ``None`` for now.

    A whole community's content is not a thing to re-read on a loop. The bound
    that actually matters for what this costs a deployment: one community-wide
    export per ``EXPORT_GUILD_COOLDOWN_HOURS``, counted across the community
    rather than per person, so a second admin does not reset it. Failed and
    expired jobs do not hold the door — only work that was really done counts.

    One definition, asked twice: the gate below refuses on it and the status
    endpoint reports it, so what the settings page says and what the door
    does cannot come apart.
    """
    if settings.EXPORT_GUILD_COOLDOWN_HOURS <= 0:
        return None
    window = timedelta(hours=settings.EXPORT_GUILD_COOLDOWN_HOURS)
    started_at = (
        await session.exec(
            select(ExportJob.created_at)
            .where(
                ExportJob.source == "guild",
                ExportJob.status.in_(
                    (
                        ExportJobStatus.queued,
                        ExportJobStatus.running,
                        ExportJobStatus.done,
                    )
                ),
                ExportJob.created_at >= datetime.now(timezone.utc) - window,
            )
            .order_by(ExportJob.created_at.desc())
            .limit(1)
        )
    ).first()
    return started_at + window if started_at is not None else None


async def _require_guild_cooldown_elapsed(session) -> None:
    """Refuse a community-wide export inside the cooldown, saying how long is
    left — the same number the settings page counts down."""
    available_at = await _guild_export_available_at(session)
    if available_at is None:
        return
    seconds_left = (available_at - datetime.now(timezone.utc)).total_seconds()
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=ExportMessages.EXPORT_COOLDOWN_ACTIVE,
        headers={"Retry-After": str(max(1, ceil(seconds_left)))},
    )


# NOTE: literal paths below must stay declared before the parametric
# ``/{job_id}`` routes, or "estimate" would be parsed as a job id.
@router.get("/estimate", response_model=BackupEstimate)
async def estimate_aggregate_export(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    scope: Literal["initiative", "guild"] = Query(),
    initiative_id: Optional[int] = Query(
        default=None, description="Required when scope=initiative"
    ),
    include_uploads: bool = Query(default=True),
) -> BackupEstimate:
    """Pre-flight numbers for the export wizard: per-tool entity counts and
    the uploads footprint (approximate — embedded document images resolve at
    build time), plus the row/byte ceilings so the client can warn before
    submitting. Guild scope requires the community's seat."""
    from app.services.export.adapters.backup import estimate_backup

    if scope == "guild":
        _require_guild_seat(guild_context)
    try:
        return await estimate_backup(
            session,
            current_user,
            guild_context.guild_id,
            scope=scope,
            initiative_id=initiative_id,
            include_uploads=include_uploads,
        )
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code)


@router.get("/initiative", response_model=None)
async def export_initiative(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: int = Query(),
    mode: Literal["backup", "report"] = Query(default="backup"),
    include: Optional[str] = Query(
        default=None,
        description=(
            'JSON object of tool→bool, e.g. {"project": true, "queue": false}. '
            "Omitted = every tool."
        ),
    ),
    formats: Optional[str] = Query(
        default=None,
        description=(
            "Report mode: JSON object of tool→format; the document entry is a "
            'nested map, e.g. {"project": "pdf", "document": {"native": "md", '
            '"spreadsheet": "xlsx"}}. Unlisted tools use their backup format.'
        ),
    ),
    include_uploads: bool = Query(
        default=True, description="Backup mode: bundle referenced upload blobs"
    ),
    tz: Optional[str] = Query(
        default=None, max_length=64, description="IANA timezone for report timestamps"
    ),
) -> Union[Response, JSONResponse]:
    """Export a whole initiative as one zip: ``backup`` bundles every included
    tool's importable JSON envelope plus a ``manifest.json`` (optionally with
    the upload blobs the documents reference); ``report`` renders each tool in
    the caller's chosen format. Requires reaching the initiative; per-entity
    sharing applies throughout, and projects are included with read access.
    Always returns ``202`` with a queued job to poll and download."""
    try:
        result = await start_export(
            session,
            user=current_user,
            guild_id=guild_context.guild_id,
            source="initiative",
            format="zip",
            params={
                "initiative_id": initiative_id,
                "mode": mode,
                "include": _parse_json_param(include),
                "formats": _parse_json_param(formats),
                "include_uploads": include_uploads,
                "tz": tz,
            },
            allow_job=_allow_job(guild_context),
        )
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code)

    job_id = None if isinstance(result, InlineExport) else result.id
    await audit_service.record(
        session,
        event_type=AuditEventType.INITIATIVE_EXPORTED,
        actor_user_id=current_user.id,
        guild_id=guild_context.guild_id,
        target_type="export_job" if job_id is not None else "initiative",
        target_id=job_id if job_id is not None else initiative_id,
        detail={
            "mode": mode,
            "include_uploads": include_uploads,
            "initiative_id": initiative_id,
            "job_id": job_id,
        },
    )
    await session.commit()

    if isinstance(result, InlineExport):  # unreachable: aggregate is always a job
        return _inline_response(result)
    return _job_response(result, status_code=status.HTTP_202_ACCEPTED)


@router.get("/guild", response_model=None)
async def export_guild(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    mode: Literal["backup", "report"] = Query(default="backup"),
    include: Optional[str] = Query(
        default=None, description="JSON object of tool→bool; omitted = every tool"
    ),
    formats: Optional[str] = Query(
        default=None,
        description="Report mode: JSON object of tool→format (see /exports/initiative)",
    ),
    include_uploads: bool = Query(
        default=True, description="Backup mode: bundle referenced upload blobs"
    ),
    tz: Optional[str] = Query(
        default=None, max_length=64, description="IANA timezone for report timestamps"
    ),
) -> Union[Response, JSONResponse]:
    """Export the whole guild — every initiative the same way
    ``/exports/initiative`` exports one, in a single zip. The community's seat
    only (held outright; the adapter re-checks at render time so a vacated
    seat fails the job closed), and once per cooldown window. Always returns
    ``202`` with a queued job to poll and download."""
    _require_guild_seat(guild_context)
    await _require_guild_cooldown_elapsed(session)
    try:
        result = await start_export(
            session,
            user=current_user,
            guild_id=guild_context.guild_id,
            source="guild",
            format="zip",
            params={
                "mode": mode,
                "include": _parse_json_param(include),
                "formats": _parse_json_param(formats),
                "include_uploads": include_uploads,
                "tz": tz,
            },
            allow_job=_allow_job(guild_context),
        )
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code)

    job_id = None if isinstance(result, InlineExport) else result.id
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_EXPORTED,
        actor_user_id=current_user.id,
        guild_id=guild_context.guild_id,
        target_type="export_job" if job_id is not None else "guild",
        target_id=job_id if job_id is not None else guild_context.guild_id,
        detail={
            "mode": mode,
            "include_uploads": include_uploads,
            "job_id": job_id,
        },
    )
    await session.commit()

    if isinstance(result, InlineExport):  # unreachable: aggregate is always a job
        return _inline_response(result)
    return _job_response(result, status_code=status.HTTP_202_ACCEPTED)


@router.get("/guild/status", response_model=GuildExportStatus)
async def read_guild_export_status(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> GuildExportStatus:
    """The state of this community's whole-community export, before anybody
    opens the wizard: the last one taken — who took it, how it ended, and
    whether its archive is still there — and when the next one may start.

    Seat-only, like the export it describes. Two bounded reads: the newest
    ``guild`` job, and the cooldown the create route enforces.
    """
    _require_guild_seat(guild_context)
    latest = (
        await session.exec(
            select(ExportJob)
            .where(ExportJob.source == "guild")
            .order_by(ExportJob.created_at.desc())
            .limit(1)
        )
    ).first()
    # Read through the member view, so a community that renders handles gets a
    # handle here as it does everywhere else. Empty where the account is gone;
    # the page says who it was missing in its own words.
    started_by = None
    if latest is not None:
        started_by = display_name(await session.get(MemberProfile, latest.created_by))
    return GuildExportStatus(
        cooldown_hours=settings.EXPORT_GUILD_COOLDOWN_HOURS,
        next_available_at=await _guild_export_available_at(session),
        latest=ExportJobRead.model_validate(latest) if latest is not None else None,
        latest_started_by=started_by or None,
    )


@router.get("/", response_model=list[ExportJobRead])
async def list_export_jobs(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> list[ExportJob]:
    """The caller's export jobs, newest first (RLS scopes the rows: own rows,
    or the whole guild for a guild admin)."""
    return list(
        await session.exec(
            select(ExportJob).order_by(ExportJob.created_at.desc()).limit(_LIST_LIMIT)
        )
    )


@router.get("/{job_id}", response_model=ExportJobRead)
async def get_export_job(
    job_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ExportJob:
    job = await session.get(ExportJob, job_id)
    if job is None:  # includes rows RLS hides — 404, never 403
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ExportMessages.EXPORT_JOB_NOT_FOUND,
        )
    return job


@router.get("/{job_id}/download")
async def download_export_artifact(
    job_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Response:
    """Stream a finished export's artifact. The RLS-gated job lookup is the
    authorization; storage is touched only after it passes."""
    job = await session.get(ExportJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ExportMessages.EXPORT_JOB_NOT_FOUND,
        )
    if job.status != ExportJobStatus.done or not job.artifact_ref:
        # A delivered job is finished and has nothing to download — it was
        # written to the operator's destination, which the job row names.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ExportMessages.EXPORT_DELIVERED
            if job.destination_ref
            else ExportMessages.EXPORT_NOT_READY,
        )
    storage = get_guild_storage(guild_context.guild_id)
    # Recover the download name from the artifact key. A named artifact
    # (passthrough / .lexical) is stored as `exports/{job_id}-{filename}`;
    # strip the `{job_id}-` prefix back off. A generic artifact is
    # `exports/{job_id}.{format}` — no such prefix, so use the generic name.
    # build_upload_response escapes the name (RFC 5987) — original filenames
    # are user text and must not break out of the header.
    basename = job.artifact_ref.rsplit("/", 1)[-1]
    named_prefix = f"{job.id}-"
    if basename.startswith(named_prefix):
        filename = basename[len(named_prefix) :]
    else:
        filename = f"{job.source}-{job.id}.{job.format}"

    # Where the operator has turned it on and the backend can sign a URL,
    # redirect to it: the bytes then travel from the object store to the
    # client instead of through this process for the length of the download.
    # The authorization is unchanged — the RLS-gated lookup above is what
    # decided this, and the URL is minted only after it passed. A filesystem
    # backend signs nothing and returns None, so those deployments keep the
    # proxied response whatever the setting says.
    signed = (
        storage.presign_get(
            job.artifact_ref,
            ttl=settings.EXPORT_DOWNLOAD_URL_TTL_SECONDS,
            filename=filename,
        )
        if settings.EXPORT_PRESIGNED_DOWNLOADS
        else None
    )
    if signed:
        return RedirectResponse(
            url=signed, status_code=status.HTTP_307_TEMPORARY_REDIRECT
        )

    blob = storage.open_readable(job.artifact_ref)
    if blob is None:  # GC'd or missing — fail closed
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ExportMessages.EXPORT_JOB_NOT_FOUND,
        )
    return build_upload_response(blob, filename=filename)
