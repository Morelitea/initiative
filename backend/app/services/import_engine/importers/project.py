"""``initiative-project`` importer — a thin adapter over the proven
``project_import.import_project`` service (one apply implementation shared
with the legacy ``POST /projects/import`` endpoint)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ImportEngineMessages
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative, PermissionKey
from app.schemas.tenant.project_export import ProjectExportEnvelope
from app.services.import_engine.contract import (
    EnvelopeImportResult,
    ImportEngineError,
)


class ProjectImporter:
    envelope_type = "initiative-project"
    permission = PermissionKey.create_projects

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        try:
            validated = ProjectExportEnvelope.model_validate(envelope)
        except ValidationError as exc:
            raise ImportEngineError(
                ImportEngineMessages.IMPORT_INVALID_ENVELOPE
            ) from exc
        # import_project applies its own version gate, but count() runs first
        # and must not trust an unsupported shape — gate here too.
        from app.schemas.tenant.project_export import (
            MIN_SUPPORTED_IMPORT_VERSION,
            SCHEMA_VERSION,
        )

        if not (
            MIN_SUPPORTED_IMPORT_VERSION <= validated.schema_version <= SCHEMA_VERSION
        ):
            raise ImportEngineError(
                ImportEngineMessages.IMPORT_SCHEMA_VERSION_UNSUPPORTED
            )
        return validated

    def count(self, validated: BaseModel) -> int:
        envelope: ProjectExportEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        return len(envelope.tasks) + 1

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
    ) -> EnvelopeImportResult:
        from app.services.tenant.project_import import import_project

        try:
            result = await import_project(
                session,
                envelope=envelope,
                target_initiative=target_initiative,
                importer=importer,
            )
        except HTTPException as exc:
            # The service speaks HTTP; the engine speaks ImportEngineError so
            # the worker can persist the code without a transport dependency.
            raise ImportEngineError(str(exc.detail), exc.status_code) from exc
        return EnvelopeImportResult(
            entity_id=result.project_id,
            entity_title=result.project_name,
            created={
                "projects": 1,
                "tasks": result.task_count,
                "tags": result.tag_create_count,
                "properties": result.property_create_count,
            },
            matched={
                "tags": result.tag_match_count,
                "properties": result.property_match_count,
                "assignees": result.assignee_match_count,
            },
            renamed_property_count=result.property_rename_count,
            unmatched_emails=result.assignee_unmatched_emails,
        )
