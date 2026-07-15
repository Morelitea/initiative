"""Import-engine contract: the per-type importer protocol and result shapes.

The engine mirrors the export engine structurally (registry → bound check →
inline-or-job), with one inversion stated once here: **imports are writes,
always** — there is no inline path for read-only actors, and every importer's
``apply`` inserts rows as the importing user.

``apply`` is flush-only: the CALLER owns the transaction (the endpoint
commits an inline apply; the worker commits a job apply; the future backup
orchestrator commits per chunk).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.schemas.base import SanitizedBaseModel


class ImportEngineError(Exception):
    """Engine-level failure with a machine-readable code (``messages.py``
    constant). Endpoints map it to an HTTPException; the worker records the
    code on the failed job row. (Named to avoid the ``ImportError`` builtin.)
    """

    def __init__(self, code: str, status_code: int = 400) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)


class EnvelopeImportResult(SanitizedBaseModel):
    """One envelope's apply outcome — JSON-serializable because it is
    persisted verbatim into ``import_jobs.result`` and rendered by the UI."""

    entity_id: int | None = None
    entity_title: str = ""
    # Row counts by noun, e.g. {"tasks": 12, "tags": 3, "events": 4}.
    created: dict[str, int] = {}
    # Existing rows reused instead of created (tags, property definitions).
    matched: dict[str, int] = {}
    # Rows that failed inside a partial-success apply (per-event savepoints),
    # by noun — structured so the UI never parses warning strings for counts.
    failed: dict[str, int] = {}
    # Property definitions that collided by name and were created renamed
    # (names when known, count always).
    renamed_properties: list[str] = []
    renamed_property_count: int = 0
    # Emails in the envelope that matched no member of the target initiative.
    unmatched_emails: list[str] = []
    warnings: list[str] = []


@dataclass
class InlineImport:
    """A small envelope applied in-request — no job row persisted (the
    mirror of the export engine's ``InlineExport``)."""

    result: EnvelopeImportResult


class EnvelopeImporter(Protocol):
    """One importer per envelope ``type`` — the registry in
    ``importers/__init__.py`` maps the discriminator to an instance."""

    # The envelope ``type`` value this importer consumes.
    envelope_type: str
    # The initiative-role permission gating the import (creating content).
    permission: str

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        """Pydantic-parse + schema_version-gate the raw envelope. Raises
        ImportEngineError(IMPORT_INVALID_ENVELOPE /
        IMPORT_SCHEMA_VERSION_UNSUPPORTED)."""
        ...

    def count(self, validated: BaseModel) -> int:
        """Cheap in-memory row proxy for the inline-vs-job split and the
        hard ceiling (len(tasks), len(items), … — 1 for a lone document)."""
        ...

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
    ) -> EnvelopeImportResult:
        """Insert the envelope's rows (importer becomes owner, owner grant
        synthesized). Flush-only — the caller commits."""
        ...
