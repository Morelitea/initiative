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
from datetime import datetime, timezone
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
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
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
        session, user=user, guild_id=guild_id, params=params, format=format
    )
    # Aggregate sources (whole-initiative/guild) declare their own ceiling —
    # a guild dump legitimately exceeds the per-report bound.
    max_rows = getattr(adapter, "max_rows", None) or settings.EXPORT_MAX_ROWS
    if row_count > max_rows:
        raise ExportError(ExportMessages.EXPORT_TOO_LARGE)

    # Aggregate sources always run as a job: their build spans many entities
    # (and possibly upload blobs), and the worker's fresh creator-routed
    # session is where the mid-build access refresh is safe.
    always_job = getattr(adapter, "always_job", False)
    if not always_job and row_count <= settings.EXPORT_INLINE_MAX_ROWS:
        from app.services.export.branding import apply_brand

        request = await adapter.build(
            session, user=user, guild_id=guild_id, params=params, format=format
        )
        request = await apply_brand(request, session)
        artifacts = await get_backend().render(request)
        artifact = _bundle(
            artifacts,
            format=format,
            stem=_bundle_stem(source, params.get("tz")),
            force_zip=getattr(adapter, "force_zip", False),
        )
        return InlineExport(
            filename=artifact.filename or f"{artifact.key}.{format}",
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
        created_by_id=user.id,
        source=source,
        template_id=adapter.template_id,
        format=format,
        params=params,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def render_to_storage(
    request: RenderRequest, *, job_id: int, source: str, tz: str | None = None
) -> str:
    """Render a job's request and persist the artifact behind the guild's
    storage backend (local FS or S3 transparently). Returns the artifact_ref
    storage key. Idempotent by job id — a re-render overwrites the same key."""
    from app.services.export.adapters import ADAPTERS

    artifacts = await get_backend().render(request)
    artifact = _bundle(
        artifacts,
        format=request.format,
        stem=_bundle_stem(source, tz),
        force_zip=getattr(ADAPTERS.get(source), "force_zip", False),
    )
    # The job id must live in the storage BASENAME, not a directory: both
    # backends flatten a key to Path(key).name (a path-traversal guard), so a
    # nested `exports/{job}/name` would drop the job id and two same-named
    # passthroughs (two members' "report.pdf") would collide. Prefix the id
    # into the name instead; the download endpoint strips `{job_id}-` back off
    # to recover the original filename for Content-Disposition.
    if artifact.filename:
        key = f"exports/{job_id}-{artifact.filename}"
    else:
        key = f"exports/{job_id}.{request.format}"
    get_guild_storage(request.guild_id).write(
        key, artifact.content, content_type=artifact.content_type
    )
    return key


def _bundle_stem(source: str, tz: str | None) -> str:
    """The zip's name shares the caller's timezone with the entry names the
    adapters produce — near-midnight exports must not disagree on the date."""
    from app.services.export.i18n import localize_now

    date = localize_now(datetime.now(timezone.utc), tz).strftime("%Y-%m-%d")
    return f"{source}-{date}"


def _bundle(
    artifacts: list[RenderedArtifact],
    *,
    format: str,
    stem: str,
    force_zip: bool = False,
) -> RenderedArtifact:
    """One artifact passes through untouched; a batch of N packages into a
    single zip (the selection-export delivery: N entities, one download).
    Entry names come from each artifact's own filename (or ``{key}.{format}``)
    and collide only when two entities share a title — deduped with a numeric
    suffix so both survive. ``force_zip`` wraps even a single artifact — a
    backup is a zip by contract (an empty initiative's backup is just its
    manifest and must still download as an importable archive)."""
    if len(artifacts) == 1 and not force_zip:
        return artifacts[0]
    if not artifacts:  # a selector that matched nothing — nothing to package
        from app.core.messages import ExportMessages

        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    import io
    import zipfile

    buffer = io.BytesIO()
    taken: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for artifact in artifacts:
            name = artifact.filename or f"{artifact.key}.{format}"
            name = _dedupe_name(name, taken)
            taken.add(name)
            archive.writestr(name, artifact.content)
    return RenderedArtifact(
        key=stem,
        content_type="application/zip",
        content=buffer.getvalue(),
        filename=f"{stem}.zip",
    )


def _dedupe_name(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    if "." in name:
        base, ext = name.rsplit(".", 1)
        pattern = f"{base} ({{n}}).{ext}"
    else:
        pattern = f"{name} ({{n}})"
    n = 2
    while pattern.format(n=n) in taken:
        n += 1
    return pattern.format(n=n)
