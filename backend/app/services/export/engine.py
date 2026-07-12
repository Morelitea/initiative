"""ExportEngine — the single shared dispatcher every export endpoint feeds.

One engine, many sources, many formats: a thin per-resource adapter queries
the data under the caller's RLS session and shapes it into a backend-agnostic
``RenderRequest``; the engine picks inline-vs-job delivery, invokes the
configured ``RenderBackend``, and confines all storage access. The engine
never makes an authorization decision — RLS already gated the rows when the
adapter queried, and the download endpoint re-gates on the ExportJob row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import func, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.platform.user import User
from app.models.tenant.export_job import ExportJob, ExportJobStatus
from app.services.export.contract import (
    RenderBackend,
    RenderedArtifact,
    RenderRequest,
)
from app.services.export.local_backend import LocalRenderBackend
from app.services.storage import get_guild_storage


# Advisory-lock namespace (arbitrary constant) for the per-user job-cap check.
_JOB_CAP_LOCK_NS = 0x455850  # "EXP"


class SourceAdapter(Protocol):
    """A per-resource export source. ``count`` is the cheap pre-render signal
    for inline-vs-job selection and the EXPORT_MAX_ROWS bound; ``build`` runs
    the real query (under the caller's RLS session — that query IS the
    authorization) and shapes the data payload."""

    source: str
    template_id: str
    formats: frozenset[str]

    async def count(
        self, session: AsyncSession, *, user: User, guild_id: int, params: dict
    ) -> int: ...

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest: ...


class ExportError(Exception):
    """Engine-level failure with a machine-readable code (``messages.py``
    constant). Endpoints map it to an HTTPException; the worker records the
    code on the failed job row."""

    def __init__(self, code: str, status_code: int = 400) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


@dataclass(frozen=True)
class InlineExport:
    """A small export rendered in-request. Deliberately persists no job row:
    an inline export is a formatted read, same surface as the list endpoint."""

    filename: str
    content_type: str
    content: bytes


def get_backend() -> RenderBackend:
    if settings.EXPORT_BACKEND == "local":
        return LocalRenderBackend()
    raise ValueError(f"Unknown EXPORT_BACKEND: {settings.EXPORT_BACKEND!r}")


def get_adapter(source: str, format: str) -> SourceAdapter:
    """Resolve a source×format combo against the registry, so unsupported
    combinations are rejected centrally."""
    from app.core.messages import ExportMessages
    from app.services.export.adapters import ADAPTERS

    adapter = ADAPTERS.get(source)
    if adapter is None:
        raise ExportError(ExportMessages.EXPORT_UNKNOWN_SOURCE, status_code=404)
    if format not in adapter.formats:
        raise ExportError(ExportMessages.EXPORT_INVALID_FORMAT)
    return adapter


async def start_export(
    session: AsyncSession,
    *,
    user: User,
    guild_id: int,
    source: str,
    format: str,
    params: dict[str, Any],
    allow_job: bool,
) -> InlineExport | ExportJob:
    """The shared create path: count under RLS, bound, then auto-select
    delivery — render inline at/under EXPORT_INLINE_MAX_ROWS, else persist a
    queued ExportJob (the filter selector only, never content) for the worker,
    which re-runs the query under the creator's RLS session at render time.

    ``allow_job`` is the caller's write-ability: a read-only actor (guild in
    read_only lifecycle, or a non-break-glass PAM grantee, who must not author
    rows) still gets inline export but cannot enqueue a job.
    """
    from app.core.messages import ExportMessages

    adapter = get_adapter(source, format)

    row_count = await adapter.count(
        session, user=user, guild_id=guild_id, params=params
    )
    if row_count > settings.EXPORT_MAX_ROWS:
        raise ExportError(ExportMessages.EXPORT_TOO_LARGE)

    if row_count <= settings.EXPORT_INLINE_MAX_ROWS:
        request = await adapter.build(
            session, user=user, guild_id=guild_id, params=params, format=format
        )
        artifacts = await get_backend().render(request)
        artifact = _single(artifacts)
        return InlineExport(
            filename=f"{artifact.key}.{format}",
            content_type=artifact.content_type,
            content=artifact.content,
        )

    if not allow_job:
        raise ExportError(ExportMessages.EXPORT_WRITE_REQUIRED, status_code=403)

    # Serialize count+insert per user so concurrent requests can't race past
    # the cap. Transaction-scoped advisory lock: released at the commit below.
    await session.exec(
        text("SELECT pg_advisory_xact_lock(:ns, :uid)"),
        params={"ns": _JOB_CAP_LOCK_NS, "uid": user.id},
    )
    active = (
        await session.exec(
            select(func.count())
            .select_from(ExportJob)
            .where(
                ExportJob.created_by_id == user.id,
                ExportJob.status.in_((ExportJobStatus.queued, ExportJobStatus.running)),
            )
        )
    ).one()
    if active >= settings.EXPORT_MAX_ACTIVE_JOBS_PER_USER:
        raise ExportError(ExportMessages.EXPORT_JOB_LIMIT_REACHED, status_code=429)

    job = ExportJob(
        guild_id=guild_id,
        created_by_id=user.id,  # ty: ignore[invalid-argument-type]
        source=source,
        template_id=adapter.template_id,
        format=format,
        params=params,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def render_to_storage(request: RenderRequest, *, job_id: int) -> str:
    """Render a job's request and persist the artifact behind the guild's
    storage backend (local FS or S3 transparently). Returns the artifact_ref
    storage key. Idempotent by job id — a re-render overwrites the same key."""
    artifacts = await get_backend().render(request)
    artifact = _single(artifacts)
    key = f"exports/{job_id}.{request.format}"
    get_guild_storage(request.guild_id).write(
        key, artifact.content, content_type=artifact.content_type
    )
    return key


def _single(artifacts: list[RenderedArtifact]) -> RenderedArtifact:
    # Bulk (batch=N) artifact packaging is not built yet; every current
    # source emits a single-item batch.
    if len(artifacts) != 1:
        raise NotImplementedError("batch-of-N artifact packaging is not built yet")
    return artifacts[0]
