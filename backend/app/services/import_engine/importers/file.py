"""``initiative-file`` importer: native, spreadsheet, smart_link, and
whiteboard envelopes. Uploaded files are backup-only (their content is a
blob under ``assets/``, not an envelope) and are rejected here."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import routed_guild_id
from app.core.messages import ImportEngineMessages
from app.core.search import SearchEntityType
from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.file import File, FileType
from app.models.tenant.initiative import Initiative, PermissionKey
from app.schemas.tenant.import_envelopes import FileEnvelope
from app.services.import_engine.common import (
    ensure_tag,
    load_initiative_member_handles,
    unique_name,
)
from app.services.import_engine.contract import (
    EnvelopeImportResult,
    ImportEngineError,
)
from app.services.import_engine.context import ImportContext
from app.services.import_engine.mentions import place_mentions
from app.services.import_engine.references import note_or_settle
from app.services.import_engine.people import PeopleMap
from app.services.import_engine.importers._base import (
    NamesPeopleInPassing,
    PropertyRestore,
    grant_ownership,
    parse_envelope,
)
from app.services.tenant import tags as tags_service
from app.services.tenant.files import (
    FileContentError,
    normalize_file_content,
)

_IMPORTABLE_TYPES = {
    FileType.native.value,
    FileType.spreadsheet.value,
    FileType.smart_link.value,
    FileType.whiteboard.value,
}


class FileImporter(NamesPeopleInPassing):
    envelope_type = tool_envelope_type(Tool.file)
    permission = PermissionKey.create_files

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        validated = parse_envelope(FileEnvelope, envelope)
        if validated.file_type not in _IMPORTABLE_TYPES:  # type: ignore[union-attr]
            # Uploaded files ride as blobs in backups, never as envelopes.
            raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_ENVELOPE)
        # Refused here rather than mid-apply, so a bad body fails the whole
        # request instead of leaving a partial import behind.
        _typed_content(validated)
        return validated

    def count(self, validated: BaseModel) -> int:
        envelope: FileEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        if envelope.file_type == FileType.spreadsheet.value:
            return len((envelope.content or {}).get("cells") or {}) or 1
        return 1

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
        context: ImportContext | None = None,
    ) -> EnvelopeImportResult:
        env: FileEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model
        guild_id = routed_guild_id(session)
        warnings: list[str] = []

        content = _decode_content(env, warnings, guild_id)
        member_handles = await load_initiative_member_handles(
            session, initiative_id=target_initiative.id
        )
        if env.file_type == FileType.native.value:
            content = place_mentions(
                content,
                env.mention_handles,
                people=context.people if context is not None else PeopleMap(),
                member_handles=member_handles,
            )

        existing_names = {
            row
            for row in (
                await session.exec(
                    select(File.name).where(File.initiative_id == target_initiative.id)
                )
            ).all()
        }
        name = unique_name(existing_names, env.name)

        file = File(
            name=name,
            file_type=FileType(env.file_type),
            content=content,
            initiative_id=target_initiative.id,
            created_by=importer.id,
        )
        session.add(file)
        await session.flush()
        # What its references name is placed once the rest of the job exists.
        file.content = note_or_settle(
            context, SearchEntityType.file, file.id, file.content
        )

        await grant_ownership(
            session,
            tool=Tool.file,
            entity_id=file.id,
            target_initiative=target_initiative,
            importer=importer,
        )

        tags_created = 0
        tags_matched = 0
        for tag_name in env.tags:
            resolved = await ensure_tag(session, name=tag_name, color="#6b7280")
            if resolved.created:
                tags_created += 1
            else:
                tags_matched += 1
            session.add(
                tags_service.tag_edge(
                    tags_service.TOOL_TAG_LINKS[Tool.file],
                    file.id,
                    resolved.id,
                )
            )

        props = PropertyRestore(
            session,
            initiative_id=target_initiative.id,
            context=context,
            member_handles=member_handles,
        )
        await props.attach(file, env.properties)
        return EnvelopeImportResult(
            entity_id=file.id,
            entity_title=file.name,
            created={
                "files": 1,
                "tags": tags_created,
                "properties": props.created,
            },
            matched={"tags": tags_matched, "properties": props.matched},
            unmatched_handles=await props.settle(file),
            warnings=warnings,
        )


def _typed_content(env: FileEnvelope) -> dict[str, Any]:
    """A non-native body, normalized exactly as the write path normalizes it:
    an imported body gets no more trust than a request body."""
    try:
        return normalize_file_content(
            env.content or {}, file_type=FileType(env.file_type)
        )
    except FileContentError as exc:
        raise ImportEngineError(exc.code) from exc


def _decode_content(
    env: FileEnvelope, warnings: list[str], guild_id: int
) -> dict[str, Any]:
    """Envelope ``content`` → the stored content model per file type."""
    if env.file_type != FileType.native.value:
        return _typed_content(env)
    content = env.content or {}
    # native: the raw editor state, stored as exported. Embedded image
    # references point at guild-local storage keys — flag ones that can't
    # resolve here (assets only travel inside backups).
    from app.services.export.lexical import blocks_from_editor_state
    from app.services.storage import get_guild_storage

    try:
        _, assets = blocks_from_editor_state(content, guild_id=guild_id)
        storage = get_guild_storage(guild_id)
        missing = [a["key"] for a in assets if storage.open_readable(a["key"]) is None]
        if missing:
            warnings.append(f"missing_embedded_images:{len(missing)}")
    except Exception:
        # Diagnostics only — never fail the import over a warning probe.
        pass
    return content
