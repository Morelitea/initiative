"""Export endpoints: create (auto inline-vs-job), poll, and download.

The artifact is content, so its download is a gated read: the download route
loads the ExportJob row under RLS (own-row + guild-admin policies) — that
lookup IS the authorization — and only then streams the file from the guild's
storage backend. Artifacts are deliberately never registered in ``uploads``,
so the guild-wide ``/uploads/{guild_id}/…`` media route cannot serve them: an
export is a per-user snapshot and may contain initiative-isolated content the
rest of the guild must not reach.
"""

from typing import Annotated, Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlmodel import select

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import ExportMessages
from app.models.platform.user import User
from app.models.tenant.export_job import ExportJob, ExportJobStatus
from app.schemas.tenant.export_job import ExportJobRead
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
    write; a regular PAM grantee must not author content (break-glass acts as
    a full guild admin and may). Inline export stays available to all — it is
    a formatted read."""
    if guild_context.content_read_only:
        return False
    if guild_context.is_pam and not guild_context.break_glass:
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
    layout: Literal["table", "checklist"] = Query(
        default="table",
        description="Markdown layout: a table, or a GitHub-style task list",
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
    project_id: int = Query(),
    format: Literal["json", "pdf", "csv", "xlsx"] = Query(default="json"),
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
            params={"project_id": project_id},
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
    document_id: int = Query(),
    format: Literal["json", "md", "csv", "xlsx", "file"] = Query(),
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
            params={"document_id": document_id},
            allow_job=_allow_job(guild_context),
        )
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code)

    if isinstance(result, InlineExport):
        return _inline_response(result)
    return _job_response(result, status_code=status.HTTP_202_ACCEPTED)


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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ExportMessages.EXPORT_NOT_READY,
        )
    blob = get_guild_storage(guild_context.guild_id).open_readable(job.artifact_ref)
    if blob is None:  # GC'd or missing — fail closed
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ExportMessages.EXPORT_JOB_NOT_FOUND,
        )
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
    return build_upload_response(blob, filename=filename)
