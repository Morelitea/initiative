"""``initiative-document`` importer: native, spreadsheet, smart_link, and
whiteboard envelopes. ``file`` documents are backup-only (their content is a
blob under ``assets/``, not an envelope) and are rejected here."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ImportEngineMessages
from app.models.platform.user import User
from app.models.tenant.document import Document, DocumentType
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.property import DocumentPropertyValue
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.tenant.tag import DocumentTag
from app.schemas.tenant.import_envelopes import DocumentEnvelope
from app.services.import_engine.common import (
    ensure_tag,
    load_initiative_member_emails,
    unique_name,
)
from app.services.import_engine.contract import (
    EnvelopeImportResult,
    ImportEngineError,
)
from app.services.import_engine.importers._base import (
    parse_envelope,
    resolve_property_values,
)

_IMPORTABLE_TYPES = {
    DocumentType.native.value,
    DocumentType.spreadsheet.value,
    DocumentType.smart_link.value,
    DocumentType.whiteboard.value,
}


class DocumentImporter:
    envelope_type = "initiative-document"
    permission = PermissionKey.create_documents

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        validated = parse_envelope(DocumentEnvelope, envelope)
        if validated.document_type not in _IMPORTABLE_TYPES:  # type: ignore[union-attr]
            # `file` documents ride as blobs in backups, never as envelopes.
            raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_ENVELOPE)
        return validated

    def count(self, validated: BaseModel) -> int:
        envelope: DocumentEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        if envelope.document_type == DocumentType.spreadsheet.value:
            return len((envelope.content or {}).get("cells") or {}) or 1
        return 1

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
    ) -> EnvelopeImportResult:
        env: DocumentEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model
        guild_id = target_initiative.guild_id
        warnings: list[str] = []

        content = _decode_content(env, warnings, guild_id)

        existing_titles = {
            row
            for row in (
                await session.exec(
                    select(Document.title).where(
                        Document.initiative_id == target_initiative.id
                    )
                )
            ).all()
        }
        title = unique_name(existing_titles, env.title)

        document = Document(
            title=title,
            document_type=DocumentType(env.document_type),
            content=content,
            initiative_id=target_initiative.id,
            guild_id=guild_id,
            created_by_id=importer.id,
            updated_by_id=importer.id,
        )
        session.add(document)
        await session.flush()

        session.add(
            ResourceGrant(
                resource_type="document",
                resource_id=document.id,
                user_id=importer.id,
                role_id=None,
                level=ResourceAccessLevel.owner,
                guild_id=guild_id,
                initiative_id=target_initiative.id,
            )
        )

        tags_created = 0
        tags_matched = 0
        for tag_name in env.tags:
            resolved = await ensure_tag(
                session, guild_id=guild_id, name=tag_name, color="#6b7280"
            )
            if resolved.created:
                tags_created += 1
            else:
                tags_matched += 1
            session.add(DocumentTag(document_id=document.id, tag_id=resolved.id))

        member_emails = await load_initiative_member_emails(
            session, initiative_id=target_initiative.id
        )
        attached = await resolve_property_values(
            session,
            initiative_id=target_initiative.id,
            values=env.properties,
            member_emails=member_emails,
        )
        for prop_id, column_kwargs in attached.column_kwargs_by_id.items():
            session.add(
                DocumentPropertyValue(
                    document_id=document.id, property_id=prop_id, **column_kwargs
                )
            )

        await session.flush()
        return EnvelopeImportResult(
            entity_id=document.id,
            entity_title=document.title,
            created={
                "documents": 1,
                "tags": tags_created,
                "properties": attached.created,
            },
            matched={"tags": tags_matched, "properties": attached.matched},
            warnings=warnings,
        )


def _decode_content(
    env: DocumentEnvelope, warnings: list[str], guild_id: int
) -> dict[str, Any]:
    """Envelope ``content`` → the stored content model per document type."""
    content = env.content or {}
    if env.document_type == DocumentType.whiteboard.value:
        # The envelope wraps the standard Excalidraw file shape; the stored
        # model is the bare scene.
        return {
            "elements": content.get("elements") or [],
            "appState": content.get("appState") or {},
            "files": content.get("files") or {},
        }
    if env.document_type == DocumentType.spreadsheet.value:
        # Same normalization as the write path — an imported snapshot gets no
        # more trust than a PUT body.
        from app.services.tenant.documents_spreadsheet import (
            normalize_spreadsheet_content,
        )

        return normalize_spreadsheet_content(content)
    if env.document_type == DocumentType.smart_link.value:
        return {"url": str(content.get("url") or "")}
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
