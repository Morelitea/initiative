"""API endpoints for importing tasks from external platforms."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import (
    RLSSessionDep,
    SessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
)
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
from app.services.tenant import import_service
from app.services import permissions as permissions_service
from app.services.tenant import task_statuses as task_statuses_service

logger = logging.getLogger(__name__)

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


async def _validate_project_write_access(
    session: SessionDep,
    project_id: int,
    user: User,
    guild_id: int,
) -> Project:
    """Validate user has write access to a project using centralized DAC."""
    project_stmt = (
        select(Project)
        .join(Project.initiative)
        .where(
            Project.id == project_id,
            Initiative.guild_id == guild_id,
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
            detail=ImportMessages.PROJECT_NOT_FOUND,
        )

    if project.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ImportMessages.PROJECT_ARCHIVED,
        )

    permissions_service.require_project_access(project, user, access="write")

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
from app.services.import_engine import engine as import_engine  # noqa: E402
from app.services.import_engine.contract import (  # noqa: E402
    ImportEngineError,
    InlineImport,
)

_LIST_LIMIT = 50


def _require_writable(guild_context: GuildContext) -> None:
    """Imports are writes, always — no inline carve-out for read-only actors
    (the inverse of the export engine's read-friendly inline path). A guild
    in read_only lifecycle can't author rows; a regular PAM grantee must not
    author content (break-glass acts as a full guild admin and may)."""
    if guild_context.content_read_only or (
        guild_context.is_pam and not guild_context.break_glass
    ):
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
    the tool's create permission there. Small envelopes apply immediately and
    return ``201`` with the result; large ones return ``202`` with a queued
    job to poll."""
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
from app.models.platform.guild import GuildRole  # noqa: E402
from app.services.import_engine import backup as backup_service  # noqa: E402
from app.services.import_engine.engine import (  # noqa: E402
    count_active_jobs_locked,
    stage_payload,
)
from app.services.tenant.attachments import (  # noqa: E402
    FileTooLargeError,
    read_upload_bounded,
)


def _require_real_guild_admin(guild_context: GuildContext) -> None:
    """Backup import creates initiatives and restores blobs — guild admins
    only, and REAL membership at that: a break-glass grant synthesizes an
    admin role, but the worker re-checks actual membership at apply time, so
    a stand-in would only fail later. Reject it up front."""
    if guild_context.grant is not None or guild_context.role != GuildRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ImportEngineMessages.IMPORT_ADMIN_REQUIRED,
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
    backups expire after IMPORT_STAGED_TTL_HOURS. Guild admins only."""
    _require_real_guild_admin(guild_context)
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
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=ImportEngineMessages.IMPORT_TOO_LARGE,
        )

    existing_names = {
        row
        for row in (
            await session.exec(
                select(Initiative.name).where(Initiative.guild_id == guild_id)
            )
        ).all()
    }
    try:
        plan = backup_service.plan_backup(
            payload, existing_initiative_names=existing_names
        )
        await count_active_jobs_locked(session, user=current_user)
        payload_ref = stage_payload(guild_id, payload, suffix="zip")
    except ImportEngineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code)

    job = ImportJob(
        guild_id=guild_id,
        created_by_id=current_user.id,
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


@router.post("/jobs/{job_id}/confirm", response_model=ImportJobRead)
async def confirm_backup_import(
    job_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    body: Optional[dict] = None,
) -> ImportJob:
    """Confirm a staged backup: flips it to ``queued`` for the worker.
    Optional body ``{"include": {tool: bool}}`` narrows which tools apply
    (omitted tools default to included). Guild admins only — re-checked here
    and again at apply time."""
    _require_real_guild_admin(guild_context)
    _require_writable(guild_context)
    job = await session.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ImportEngineMessages.IMPORT_JOB_NOT_FOUND,
        )
    if job.status != ImportJobStatus.staged or job.source != "backup":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ImportEngineMessages.IMPORT_NOT_CONFIRMABLE,
        )
    include = (body or {}).get("include")
    if include is not None:
        if not isinstance(include, dict) or not all(
            isinstance(v, bool) for v in include.values()
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ImportEngineMessages.IMPORT_INVALID_PARAMS,
            )
        job.params = {**(job.params or {}), "include": include}
    job.status = ImportJobStatus.queued
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job
