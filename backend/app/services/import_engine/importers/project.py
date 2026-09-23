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
from app.schemas.tenant.backup_export import ManifestPerson
from app.schemas.tenant.project_export import ProjectExportEnvelope
from app.services.import_engine.contract import (
    EnvelopeImportResult,
    ImportEngineError,
)
from app.services.import_engine.common import handle_key
from app.services.import_engine.context import ImportContext
from app.services.import_engine.people import user_reference_handles


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
        # A comment is a row like any other, so it counts against the
        # ceiling: a project with ten tasks and four thousand comments on
        # them is a large import however few tasks it names.
        return (
            len(envelope.tasks) + sum(len(task.comments) for task in envelope.tasks) + 1
        )

    def people(self, validated: BaseModel) -> list[ManifestPerson]:
        """Everybody this project names, most-quoted first.

        The same inventory a backup's manifest carries, taken from one
        envelope: a handle, the name it went by, and how many comments hang
        on getting that one row right. Three kinds of mention put somebody on
        it, because all three go through the answer the wizard records:

        * a comment's author, whose words land under whoever the handle is
          mapped to;
        * an assignee, whose task lands on whoever the handle is mapped to —
          still only if that account is in the target initiative (see
          ``people.initiative_member_id``);
        * a user-type property value — a Reporter, a Reviewer — placed by
          the same rule as an assignee.

        An assignee who wrote nothing is still a question worth asking. Left
        off, a handle nobody here answers to by name was applied without the
        step and reported afterwards as unmatched, with no way to say who it
        was.

        A handle the envelope spelled two ways is one person: it is keyed
        the way it is matched, and the first spelling seen is the one shown.
        """
        envelope: ProjectExportEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        seen: dict[str, ManifestPerson] = {}

        def note(handle: str | None, name: str | None, comments: int) -> None:
            handle = (handle or "").strip()
            if not handle:
                return
            key = handle_key(handle)
            person = seen.get(key)
            if person is None:
                seen[key] = ManifestPerson(
                    handle=handle, name=name, comment_count=comments
                )
                return
            person.comment_count += comments
            # A name only where one was given: the first mention of somebody
            # may be the one that carried no display name.
            if person.name is None:
                person.name = name

        for task in envelope.tasks:
            for comment in task.comments:
                note(comment.author_handle, comment.author_name, 1)
            for handle in task.assignee_handles:
                note(handle, None, 0)
        # A user-type property — a Reporter, a Reviewer — is placed through
        # the same answer an assignee is, so it is asked about the same way.
        for handle in user_reference_handles(envelope.model_dump(mode="json")):
            note(handle, None, 0)
        return sorted(seen.values(), key=lambda p: (-p.comment_count, p.handle.lower()))

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
        context: ImportContext | None = None,
    ) -> EnvelopeImportResult:
        from app.services.tenant.project_import import import_project

        try:
            result = await import_project(
                session,
                envelope=envelope,
                target_initiative=target_initiative,
                importer=importer,
                context=context,
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
                "comments": result.comment_count,
            },
            matched={
                "tags": result.tag_match_count,
                "properties": result.property_match_count,
                "assignees": result.assignee_match_count,
            },
            renamed_property_count=result.property_rename_count,
            unmatched_handles=result.assignee_unmatched_handles,
        )
