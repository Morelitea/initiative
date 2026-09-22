"""API endpoints for importing tasks from external platforms."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
)
from app.models.platform.guild import GuildRole
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.initiative import Initiative
from app.models.platform.user import User
from app.schemas.tenant.import_data import (
    TodoistImportRequest,
    TodoistParseResult,
    VikunjaImportRequest,
    VikunjaParseResult,
    TickTickImportRequest,
    TickTickParseResult,
    ImportResult,
)
from app.core.messages import ImportMessages
from app.core.tools import Tool
from app.services.tenant import import_service
from app.services import permissions as permissions_service
from app.services.tenant import filter_presets as filter_presets_service
from app.services.tenant import task_statuses as task_statuses_service

logger = logging.getLogger(__name__)

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


async def _validate_project_write_access(
    session: AsyncSession,
    project_id: int,
    user: User,
    guild_id: int,
) -> Project:
    """Validate user has write access to a project using centralized DAC.

    Takes a plain session: this is a helper the handlers call, not a route
    dependency, so it accepts whichever session its caller is already using
    (the guild-routed one, in every case today).
    """
    project_stmt = (
        select(Project)
        .join(Project.initiative)
        .where(
            Project.id == project_id,
        )
        .options(
            selectinload(Project.grants).selectinload(ResourceGrant.role),
            selectinload(Project.initiative).selectinload(Initiative.memberships),
        )
    )
    result = await session.exec(project_stmt)
    project = result.first()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=Tool.project.not_found_code,
        )

    if project.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ImportMessages.PROJECT_ARCHIVED,
        )

    permissions_service.require_access(
        permissions_service.DAC_RESOURCES[Tool.project], project, user, access="write"
    )

    return project


@router.post("/todoist/parse", response_model=TodoistParseResult)
async def parse_todoist_csv(
    csv_content: Annotated[str, Body(media_type="text/plain")],
    _current_user: Annotated[User, Depends(get_current_active_user)],
    _guild_context: GuildContextDep,
) -> TodoistParseResult:
    """
    Parse a Todoist CSV export and return detected sections and task count.

    This is a preview endpoint to help users map sections before importing.
    """
    try:
        parse_result, _ = import_service.parse_todoist_csv(csv_content)
        return parse_result
    except Exception:
        logger.warning("import parse failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ImportMessages.PARSE_FAILED,
        )


@router.post("/todoist", response_model=ImportResult)
async def import_from_todoist(
    request: TodoistImportRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ImportResult:
    """
    Import tasks from a Todoist CSV export into a project.

    The section_mapping maps Todoist section names to task_status_id values
    in the target project.
    """
    # Validate write access to the project
    project = await _validate_project_write_access(
        session,
        request.project_id,
        current_user,
        guild_context.guild_id,
    )

    # Ensure default statuses exist
    await task_statuses_service.ensure_default_statuses(session, project.id)
    await filter_presets_service.ensure_default_presets(session, project.id)

    # Validate that all mapped status IDs belong to the project
    project_statuses = await task_statuses_service.list_statuses(session, project.id)
    valid_status_ids = {s.id for s in project_statuses}

    for section_name, status_id in request.section_mapping.items():
        if status_id not in valid_status_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status ID {status_id} for section '{section_name}'",
            )

    # Perform the import
    result = await import_service.import_todoist_tasks(
        session,
        project.id,
        request.csv_content,
        request.section_mapping,
    )

    return result


@router.post("/vikunja/parse", response_model=VikunjaParseResult)
async def parse_vikunja_json(
    json_content: Annotated[str, Body(media_type="text/plain")],
    _current_user: Annotated[User, Depends(get_current_active_user)],
    _guild_context: GuildContextDep,
) -> VikunjaParseResult:
    """
    Parse a Vikunja JSON export and return detected projects with buckets.

    This is a preview endpoint to help users select a project and map buckets.
    """
    try:
        return import_service.parse_vikunja_json(json_content)
    except Exception:
        logger.warning("import parse failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ImportMessages.PARSE_FAILED,
        )


@router.post("/vikunja", response_model=ImportResult)
async def import_from_vikunja(
    request: VikunjaImportRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ImportResult:
    """
    Import tasks from a Vikunja JSON export into a project.

    The bucket_mapping maps Vikunja bucket IDs to task_status_id values
    in the target project.
    """
    # Validate write access to the project
    project = await _validate_project_write_access(
        session,
        request.project_id,
        current_user,
        guild_context.guild_id,
    )

    # Ensure default statuses exist
    await task_statuses_service.ensure_default_statuses(session, project.id)
    await filter_presets_service.ensure_default_presets(session, project.id)

    # Validate that all mapped status IDs belong to the project
    project_statuses = await task_statuses_service.list_statuses(session, project.id)
    valid_status_ids = {s.id for s in project_statuses}

    for bucket_id, status_id in request.bucket_mapping.items():
        if status_id not in valid_status_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status ID {status_id} for bucket {bucket_id}",
            )

    # Perform the import
    result = await import_service.import_vikunja_tasks(
        session,
        project.id,
        request.json_content,
        request.source_project_id,
        request.bucket_mapping,
    )

    return result


@router.post("/ticktick/parse", response_model=TickTickParseResult)
async def parse_ticktick_csv(
    csv_content: Annotated[str, Body(media_type="text/plain")],
    _current_user: Annotated[User, Depends(get_current_active_user)],
    _guild_context: GuildContextDep,
) -> TickTickParseResult:
    """
    Parse a TickTick CSV export and return detected lists with columns.

    This is a preview endpoint to help users select a list and map columns.
    """
    try:
        return import_service.parse_ticktick_csv(csv_content)
    except Exception:
        logger.warning("import parse failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ImportMessages.PARSE_FAILED,
        )


@router.post("/ticktick", response_model=ImportResult)
async def import_from_ticktick(
    request: TickTickImportRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ImportResult:
    """
    Import tasks from a TickTick CSV export into a project.

    The column_mapping maps TickTick column names to task_status_id values
    in the target project.
    """
    # Validate write access to the project
    project = await _validate_project_write_access(
        session,
        request.project_id,
        current_user,
        guild_context.guild_id,
    )

    # Ensure default statuses exist
    await task_statuses_service.ensure_default_statuses(session, project.id)
    await filter_presets_service.ensure_default_presets(session, project.id)

    # Validate that all mapped status IDs belong to the project
    project_statuses = await task_statuses_service.list_statuses(session, project.id)
    valid_status_ids = {s.id for s in project_statuses}

    for column_name, status_id in request.column_mapping.items():
        if status_id not in valid_status_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status ID {status_id} for column '{column_name}'",
            )

    # Perform the import
    result = await import_service.import_ticktick_tasks(
        session,
        project.id,
        request.csv_content,
        request.source_list_name,
        request.column_mapping,
    )

    return result


# ---------------------------------------------------------------------------
# Import engine: envelope imports + job lifecycle
# ---------------------------------------------------------------------------
# NOTE: the engine routes use literal paths plus a parametric /{job_id};
# every literal route MUST stay declared before the parametric ones.

from fastapi import Response  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from app.core.messages import ImportEngineMessages  # noqa: E402
from app.models.tenant.import_job import ImportJob, ImportJobStatus  # noqa: E402
from app.schemas.tenant.import_job import (  # noqa: E402
    EnvelopeImportRequest,
    EnvelopeImportResponse,
    ImportJobRead,
)
from app.schemas.tenant.atlassian import (  # noqa: E402
    AtlassianConnectRequest,
    AtlassianConnectResponse,
)
from app.services.import_engine import atlassian as atlassian_service  # noqa: E402
from app.services.import_engine import credentials as import_credentials  # noqa: E402
from app.services.import_engine import engine as import_engine  # noqa: E402
from app.services.import_engine.contract import (  # noqa: E402
    ImportEngineError,
    InlineImport,
)

_LIST_LIMIT = 50


def _job_credential_id(job: ImportJob) -> int | None:
    """The credential this job was lent, if it was lent one. ``params`` is
    JSON that round-tripped through a request, so the value is checked rather
    than trusted."""
    raw = (job.params or {}).get("credential_id")
    return raw if isinstance(raw, int) else None


def _require_writable(guild_context: GuildContext) -> None:
    """Imports are writes, always — no inline carve-out for read-only actors
    (the inverse of the export engine's read-friendly inline path). A guild in
    read_only lifecycle can't author rows, and neither can a grantee: a grant
    reaches existing content, whatever level it carries."""
    if guild_context.content_read_only or guild_context.is_pam:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ImportEngineMessages.IMPORT_WRITE_REQUIRED,
        )


@router.post("/envelope", response_model=None, status_code=status.HTTP_201_CREATED)
async def import_envelope(
    payload: EnvelopeImportRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Response:
    """Import a previously-exported JSON envelope (any tool — the envelope's
    ``type`` field selects the importer) into the chosen initiative. Requires
    the tool's create permission there.

    Small envelopes apply immediately and return ``201`` with the result.
    Anything else returns ``202`` with a job: ``queued`` for one that is
    merely large, or ``staged`` for one quoting people nobody here can place,
    whose ``plan`` names them and which starts on
    ``POST /imports/jobs/{id}/confirm``."""
    # Byte bound (IMPORT_MAX_ENVELOPE_BYTES) is enforced by
    # BodySizeLimitMiddleware at the ASGI seam — a handler-level check would
    # run only after FastAPI had already buffered and parsed the body.
    _require_writable(guild_context)
    try:
        outcome = await import_engine.start_envelope_import(
            session,
            user=current_user,
            guild_id=guild_context.guild_id,
            initiative_id=payload.initiative_id,
            envelope=payload.envelope,
        )
    except ImportEngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code)

    if isinstance(outcome, InlineImport):
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=EnvelopeImportResponse(result=outcome.result).model_dump(
                mode="json"
            ),
        )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=ImportJobRead.model_validate(outcome).model_dump(mode="json"),
    )


@router.post(
    "/atlassian/connect",
    response_model=AtlassianConnectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def connect_atlassian(
    payload: AtlassianConnectRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> AtlassianConnectResponse:
    """Prove an Atlassian API token and say what the site holds.

    One request, because the two questions are the same one: the only honest
    proof that a token works is using it, so connecting *is* the first
    listing. It returns the Jira projects and Confluence spaces the token can
    see, with rough counts, and the id of the stored credential the later
    confirm quotes.

    The credential is stored **after** the site answers, never before — a
    token the site rejects is not worth a row. What is stored is short-lived
    by construction: it carries the secret to the worker that picks the job
    up and is deleted when that job ends, or swept at its deadline if no job
    ever claims it.

    Real membership of a writable guild, like every other import entry point.
    Which initiative the work lands in is not asked here and not trusted from
    here — the target and the create permission for it are resolved on the
    confirm, and again by the worker at apply time.
    """
    _require_writable(guild_context)
    if guild_context.grant is not None:
        # A break-glass or support grant reaches existing content; it does not
        # get to make this server talk to somebody else's on its behalf.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ImportEngineMessages.IMPORT_WRITE_REQUIRED,
        )

    try:
        credential = atlassian_service.AtlassianCredential(
            site_url=atlassian_service.normalize_site_url(payload.site_url),
            email=payload.email.strip(),
            api_token=payload.api_token,
        )
        jira, confluence = await atlassian_service.probe_site(credential)
    except ImportEngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code)

    credential_id = await import_credentials.store(
        guild_id=guild_context.guild_id,
        user_id=current_user.id,
        provider="atlassian",
        site_url=credential.site_url,
        principal=credential.email,
        secret=credential.api_token,
    )
    return AtlassianConnectResponse(
        credential_id=credential_id,
        site_url=credential.site_url,
        jira=jira,
        confluence=confluence,
    )


@router.get("/jobs", response_model=list[ImportJobRead])
async def list_import_jobs(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> list[ImportJob]:
    """The caller's import jobs, newest first (RLS scopes the rows: own rows,
    or the whole guild for a guild admin)."""
    return list(
        await session.exec(
            select(ImportJob).order_by(ImportJob.created_at.desc()).limit(_LIST_LIMIT)
        )
    )


@router.get("/jobs/{job_id}", response_model=ImportJobRead)
async def get_import_job(
    job_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ImportJob:
    job = await session.get(ImportJob, job_id)
    if job is None:  # includes rows RLS hides — 404, never 403
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ImportEngineMessages.IMPORT_JOB_NOT_FOUND,
        )
    return job


@router.delete("/jobs/{job_id}", response_model=ImportJobRead)
async def cancel_import_job(
    job_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ImportJob:
    """Cancel a job that hasn't started applying (staged or queued); its
    staged payload is deleted. A running/terminal job is not cancellable —
    409 (an interrupted apply would leave half-committed content)."""
    job = await session.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ImportEngineMessages.IMPORT_JOB_NOT_FOUND,
        )
    if job.status not in (ImportJobStatus.staged, ImportJobStatus.queued):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ImportEngineMessages.IMPORT_NOT_CANCELLABLE,
        )
    import_engine.delete_payload(guild_context.guild_id, job.payload_ref)
    # Everything the job was lent goes back with the payload — a cancelled
    # import has no further use for the credential it was given.
    await import_credentials.discard(_job_credential_id(job))
    job.status = ImportJobStatus.cancelled
    job.payload_ref = None
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


# ---------------------------------------------------------------------------
# Backup-zip imports (guild admin only)
# ---------------------------------------------------------------------------

from fastapi import File, UploadFile  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.import_engine import backup as backup_service  # noqa: E402
from app.services.import_engine.engine import (  # noqa: E402
    count_active_jobs_locked,
    stage_payload,
)
from app.services.tenant.attachments import (  # noqa: E402
    FileTooLargeError,
    read_upload_bounded,
)


def _require_guild_seat(guild_context: GuildContext) -> None:
    """Restoring a backup creates initiatives and writes blobs back into the
    community, so it sits with the seat that exports one.

    Held outright, too: a break-glass grant synthesizes an admin role, but the
    worker re-checks real membership at apply time, so a stand-in would only
    fail later. Reject it up front.
    """
    if guild_context.is_pam or guild_context.role is not GuildRole.superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ImportEngineMessages.IMPORT_SUPERADMIN_REQUIRED,
        )


@router.post(
    "/backup", response_model=ImportJobRead, status_code=status.HTTP_201_CREATED
)
async def upload_backup(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    file: UploadFile = File(...),
) -> ImportJob:
    """Upload a backup zip and get its pre-flight plan. The zip is staged in
    guild storage and the job parked as ``staged`` (nothing is imported yet);
    ``POST /imports/jobs/{id}/confirm`` starts the apply. Unconfirmed staged
    backups expire after IMPORT_STAGED_TTL_HOURS. The community's seat only."""
    _require_guild_seat(guild_context)
    _require_writable(guild_context)
    guild_id = guild_context.guild_id

    # Byte cap: BodySizeLimitMiddleware already rejected an oversized or
    # chunked-over-cap request at the ASGI seam; this bounded read is the
    # in-process backstop.
    try:
        payload = await read_upload_bounded(
            file, settings.IMPORT_MAX_BACKUP_UPLOAD_BYTES
        )
    except FileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=ImportEngineMessages.IMPORT_TOO_LARGE,
        )

    existing_names = {
        row for row in (await session.exec(select(Initiative.name))).all()
    }
    # The guild's own roster, so the plan can suggest who each name in the
    # archive is. Read on the request's routed session, so it is the roster
    # this user can actually see.
    roster = await _guild_member_ids_by_handle(session, guild_id)
    try:
        plan = backup_service.plan_backup(
            payload,
            existing_initiative_names=existing_names,
            member_ids_by_handle=roster,
        )
        await count_active_jobs_locked(session, user=current_user)
        payload_ref = stage_payload(guild_id, payload, suffix="zip")
    except ImportEngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code)

    job = ImportJob(
        created_by=current_user.id,
        source="backup",
        params={},
        payload_ref=payload_ref,
        plan=plan.model_dump(mode="json"),
        status=ImportJobStatus.staged,
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=settings.IMPORT_STAGED_TTL_HOURS),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _guild_member_ids_by_handle(session, guild_id: int) -> dict[str, int]:
    """Every member of this guild, keyed by normalised handle.

    One query rather than a lookup per person: an archive can quote dozens of
    names, and the answer for all of them is the same roster.
    """
    from app.core.user_display import handle_of
    from app.models.platform.guild import GuildMembership
    from app.models.platform.user_profile_view import MemberProfile
    from app.services.import_engine.common import handle_key

    # ``MemberProfile``, not ``users``: this runs on the guild-routed session,
    # and the view is how guild content refers to a person. The table itself
    # is the account holder's own business.
    rows = (
        await session.exec(
            select(MemberProfile)
            .join(GuildMembership, GuildMembership.user_id == MemberProfile.id)
            .where(GuildMembership.guild_id == guild_id)
        )
    ).all()
    return {handle_key(handle_of(row)): row.id for row in rows}


@router.post("/jobs/{job_id}/confirm", response_model=ImportJobRead)
async def confirm_import(
    job_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    body: Optional[dict] = None,
) -> ImportJob:
    """Confirm a staged import: flips it to ``queued`` for the worker.

    Optional body ``{"include": {tool: bool}}`` narrows which tools apply
    (backup only; omitted tools default to included), and ``{"people_map":
    {handle: user id}}`` says who each name the archive quotes is here — the
    answers to the wizard's people step. Both are recorded on the job and read
    at apply time; the mapping is re-checked against real membership there,
    because this confirm may be hours old by then.

    Two kinds of job reach this, and they are gated differently because they
    were created differently. A **backup** puts a whole community back, so it
    is the seat only — re-checked here and again at apply time. A lone
    **envelope** is one thing its creator already had the create permission
    for when they dropped it; it is staged only to ask who the handles in it
    are, so that creator is the one who answers, and nobody else confirms on
    their behalf."""
    _require_writable(guild_context)
    job = await session.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ImportEngineMessages.IMPORT_JOB_NOT_FOUND,
        )
    if job.source == "backup":
        _require_guild_seat(guild_context)
    elif job.created_by != current_user.id:
        # RLS lets a guild admin read the row; answering somebody else's
        # people step is a different thing from being able to see it.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ImportEngineMessages.IMPORT_NOT_CONFIRMABLE,
        )
    if job.status != ImportJobStatus.staged:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ImportEngineMessages.IMPORT_NOT_CONFIRMABLE,
        )
    # A staged job whose TTL already elapsed is expired NOW, not silently on
    # GC's next pass: confirming it would return 200 and then vanish queued
    # (GC sweeps expired queued rows too) with no notification.
    now = datetime.now(timezone.utc)
    if job.expires_at is not None and job.expires_at <= now:
        import_engine.delete_payload(guild_context.guild_id, job.payload_ref)
        await import_credentials.discard(_job_credential_id(job))
        job.status = ImportJobStatus.expired
        job.payload_ref = None
        session.add(job)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ImportEngineMessages.IMPORT_NOT_CONFIRMABLE,
        )
    include = (body or {}).get("include") if job.source == "backup" else None
    if include is not None:
        if not isinstance(include, dict) or not all(
            isinstance(v, bool) for v in include.values()
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ImportEngineMessages.IMPORT_INVALID_PARAMS,
            )
        job.params = {**(job.params or {}), "include": include}
    people_map = (body or {}).get("people_map")
    if people_map is not None:
        if not isinstance(people_map, dict) or not all(
            isinstance(handle, str) and isinstance(user_id, int)
            for handle, user_id in people_map.items()
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ImportEngineMessages.IMPORT_INVALID_PARAMS,
            )
        # Stored as given; the ids are proved to be members of this guild at
        # apply time, on the session that will actually write the rows.
        job.params = {**(job.params or {}), "people_map": people_map}
    job.status = ImportJobStatus.queued
    # Fresh TTL window: the confirmed job now waits on the worker, and a
    # nearly-elapsed staging TTL must not let GC sweep it out of the queue.
    job.expires_at = now + timedelta(hours=settings.IMPORT_STAGED_TTL_HOURS)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job
