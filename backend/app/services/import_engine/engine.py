"""Import engine: the shared create path for envelope imports.

Mirrors the export engine's ``start_export`` (registry → bound → inline-or-
job with an advisory-locked per-user cap) with one inversion: **imports are
writes, always** — the caller must already be a writable actor (endpoints
enforce it), and every apply inserts rows as the importing user.

A payload too large to apply inline is staged behind the guild's storage
backend (the job row references it and never holds content) and applied by
the worker on a fresh creator-routed session.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import ImportEngineMessages
from app.models.platform.user import User
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.models.tenant.initiative import Initiative
from app.core.tools import CORE_TOOLS, tool_for_create_permission
from app.services.import_engine.contract import (
    EnvelopeImporter,
    ImportEngineError,
    InlineImport,
)

# Distinct namespace from the export engine's lock so the two caps don't
# serialize against each other.
_JOB_CAP_LOCK_NS = 0x494D50  # "IMP"

# Statuses that count against the per-user active-job cap.
_ACTIVE_STATUSES = (
    ImportJobStatus.staged,
    ImportJobStatus.queued,
    ImportJobStatus.running,
)


def get_importer(envelope_type: str) -> EnvelopeImporter:
    from app.services.import_engine.importers import IMPORTERS

    importer = IMPORTERS.get(envelope_type)
    if importer is None:
        raise ImportEngineError(ImportEngineMessages.IMPORT_UNKNOWN_TYPE)
    return importer


async def load_target_initiative(
    session: AsyncSession,
    *,
    guild_id: int,
    initiative_id: Any,
    importer: EnvelopeImporter,
    user: User,
) -> Initiative:
    """Resolve + authorize the import target: the initiative must be
    reachable under the caller's RLS (unreachable is indistinguishable from
    absent — 404), its tool master switch must be on, and the caller must
    hold the importer's create permission (guild admins bypass, like every
    create path)."""
    from app.models.tenant.initiative import PermissionKey
    from app.services import rls as rls_service
    from app.services.platform import guilds as guilds_service

    try:
        initiative_id = int(initiative_id)
    except (TypeError, ValueError):
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_PARAMS)

    initiative = (
        await session.exec(
            select(Initiative).where(
                Initiative.id == initiative_id,
                Initiative.guild_id == guild_id,
            )
        )
    ).one_or_none()
    if initiative is None:
        raise ImportEngineError(
            ImportEngineMessages.IMPORT_INVALID_PARAMS, status_code=404
        )

    # Tool master switch, derived from the Tool enum (the single source of
    # the create_*/​*_enabled naming) — never by string surgery on the
    # permission key. Registry construction already proved the mapping exists
    # (importers/__init__.py), so a miss here is impossible, not "default on".
    permission = PermissionKey(importer.permission)
    tool = tool_for_create_permission(permission.value)
    if tool not in CORE_TOOLS and not getattr(initiative, tool.view_permission):
        raise ImportEngineError(
            ImportEngineMessages.IMPORT_TOOL_DISABLED, status_code=400
        )

    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=user.id
    )
    is_admin = membership is not None and rls_service.is_guild_admin(membership.role)
    if not is_admin:
        has_perm = await rls_service.check_initiative_permission(
            session,
            initiative_id=initiative.id,
            user=user,
            permission_key=permission,
        )
        if not has_perm:
            raise ImportEngineError(
                ImportEngineMessages.IMPORT_PERMISSION_REQUIRED, status_code=403
            )
    return initiative


async def start_envelope_import(
    session: AsyncSession,
    *,
    user: User,
    guild_id: int,
    initiative_id: int,
    envelope: dict[str, Any],
) -> InlineImport | ImportJob:
    """The shared create path: validate + authorize under RLS, bound, then
    auto-select delivery — apply in-request at/under IMPORT_INLINE_MAX_ROWS,
    else stage the payload and persist a queued ImportJob for the worker,
    which re-validates and applies under the creator's RLS session."""
    envelope_type = envelope.get("type") or envelope.get("kind")
    if not isinstance(envelope_type, str):
        raise ImportEngineError(ImportEngineMessages.IMPORT_UNKNOWN_TYPE)
    importer = get_importer(envelope_type)
    validated = importer.validate(envelope)
    initiative = await load_target_initiative(
        session,
        guild_id=guild_id,
        initiative_id=initiative_id,
        importer=importer,
        user=user,
    )

    rows = importer.count(validated)
    if rows > settings.IMPORT_MAX_ROWS:
        raise ImportEngineError(ImportEngineMessages.IMPORT_TOO_LARGE)

    if rows <= settings.IMPORT_INLINE_MAX_ROWS:
        result = await importer.apply(
            session,
            envelope=validated,
            target_initiative=initiative,
            importer=user,
        )
        await session.commit()
        return InlineImport(result=result)

    # Serialize count+insert per user so concurrent requests can't race past
    # the cap. Transaction-scoped advisory lock: released at the commit below.
    await session.exec(
        text("SELECT pg_advisory_xact_lock(:ns, :uid)"),
        params={"ns": _JOB_CAP_LOCK_NS, "uid": user.id},
    )
    active = (
        await session.exec(
            select(func.count())
            .select_from(ImportJob)
            .where(
                ImportJob.created_by_id == user.id,
                ImportJob.status.in_(_ACTIVE_STATUSES),
            )
        )
    ).one()
    if active >= settings.IMPORT_MAX_ACTIVE_JOBS_PER_USER:
        raise ImportEngineError(
            ImportEngineMessages.IMPORT_JOB_LIMIT_REACHED, status_code=429
        )

    payload_ref = stage_payload(
        guild_id, json.dumps(envelope).encode("utf-8"), suffix="json"
    )
    job = ImportJob(
        guild_id=guild_id,
        created_by_id=user.id,
        source=envelope_type,
        params={"initiative_id": initiative.id},
        payload_ref=payload_ref,
        status=ImportJobStatus.queued,
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=settings.IMPORT_STAGED_TTL_HOURS),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


def stage_payload(guild_id: int, payload: bytes, *, suffix: str) -> str:
    """Write an import payload behind the guild's storage backend and return
    its key. Payloads are deliberately NOT registered in ``uploads`` — they
    are engine-internal, unreachable via the media route, and deleted when
    the job reaches a terminal state (or by GC on expiry)."""
    from app.services.storage import get_guild_storage

    key = f"imports/{uuid.uuid4().hex}.{suffix}"
    content_type = "application/json" if suffix == "json" else "application/zip"
    get_guild_storage(guild_id).write(key, payload, content_type=content_type)
    return key


def read_payload(guild_id: int, payload_ref: str) -> bytes | None:
    """Read a staged payload back from the guild's storage backend (local FS
    path or S3 stream transparently). None when the blob is gone."""
    from pathlib import Path

    from app.services.storage import get_guild_storage

    blob = get_guild_storage(guild_id).open_readable(payload_ref)
    if blob is None:
        return None
    if blob.path is not None:
        return Path(blob.path).read_bytes()
    return blob.stream.read()  # type: ignore[union-attr]


def delete_payload(guild_id: int, payload_ref: str | None) -> None:
    """Best-effort staged-payload cleanup — a failing delete must not fail
    the job transition (GC re-tries expired rows)."""
    if not payload_ref:
        return
    from app.services.storage import get_guild_storage

    try:
        get_guild_storage(guild_id).delete(payload_ref)
    except Exception:  # pragma: no cover - backend-specific failures
        pass
