from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.comment import Comment
from app.models.tenant.document import (
    Document,
    DocumentType,
)
from app.models.tenant.upload import Upload
from app.models.tenant.initiative import (
    Initiative,
    InitiativeMember,
    InitiativeRoleModel,
)
from app.models.tenant.property import DocumentPropertyValue
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.core.config import settings
from app.core.references import unresolve_wikilinks_to
from app.core.tools import Tool
from app.core.messages import DocumentMessages
from app.services.tenant import attachments as attachments_service
from app.services.tenant import tags as tags_service
from app.services.tenant.collaboration import collaboration_manager
from app.db.session import routed_guild_id


def _empty_paragraph() -> dict[str, Any]:
    return {
        "children": [],
        "direction": None,
        "format": "",
        "indent": 0,
        "type": "paragraph",
        "version": 1,
    }


def _empty_state() -> dict[str, Any]:
    return {
        "root": {
            "children": [_empty_paragraph()],
            "direction": None,
            "format": "",
            "indent": 0,
            "type": "root",
            "version": 1,
        }
    }


EMPTY_LEXICAL_STATE = _empty_state()


class DocumentContentError(ValueError):
    """Raised when document content fails type-specific validation.

    The `code` attribute is a stable error constant from DocumentMessages
    that callers (endpoints) translate to a localized HTTPException.
    Inheriting from ValueError keeps bare ``except ValueError`` catches
    working for callers that don't care about the structured code.
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def normalize_document_content(
    payload: dict[str, Any] | None,
    *,
    document_type: DocumentType = DocumentType.native,
) -> dict[str, Any]:
    """Normalize content JSONB based on document type.

    - native: ensure a Lexical root with at least one paragraph child
    - whiteboard: ensure the Excalidraw scene shape {elements, appState, files}
    - file: content is just a passthrough dict (usually empty)
    """
    if document_type == DocumentType.file:
        return payload if isinstance(payload, dict) else {}

    if document_type == DocumentType.whiteboard:
        if not isinstance(payload, dict):
            return {"elements": [], "appState": {}, "files": {}}
        return {
            "elements": payload.get("elements") or [],
            "appState": payload.get("appState") or {},
            "files": payload.get("files") or {},
        }

    if document_type == DocumentType.smart_link:
        if not isinstance(payload, dict):
            raise DocumentContentError(DocumentMessages.SMART_LINK_URL_REQUIRED)
        url = str(payload.get("url") or "").strip()
        if not url:
            raise DocumentContentError(DocumentMessages.SMART_LINK_URL_REQUIRED)
        if not (url.startswith("http://") or url.startswith("https://")):
            raise DocumentContentError(DocumentMessages.SMART_LINK_URL_INVALID)
        return {"url": url}

    if document_type == DocumentType.spreadsheet:
        # Imported lazily to avoid a circular import: documents_spreadsheet
        # imports DocumentContentError from this module.
        from app.services.tenant.documents_spreadsheet import (
            normalize_spreadsheet_content,
        )

        return normalize_spreadsheet_content(payload)

    # native (default)
    if not isinstance(payload, dict):
        return deepcopy(EMPTY_LEXICAL_STATE)
    root = payload.get("root")
    if not isinstance(root, dict):
        payload["root"] = deepcopy(EMPTY_LEXICAL_STATE["root"])
        return payload
    children = root.get("children")
    if not isinstance(children, list) or not children:
        root["children"] = [_empty_paragraph()]
    return payload


async def get_document(
    session: AsyncSession,
    *,
    document_id: int,
    guild_id: int,
    populate_existing: bool = False,
) -> Document | None:
    statement = (
        select(Document)
        .join(Document.initiative)
        .where(
            Document.id == document_id,
            Initiative.guild_id == guild_id,
        )
        .options(
            selectinload(Document.initiative)
            .selectinload(Initiative.memberships)
            .options(
                selectinload(InitiativeMember.user),
                selectinload(InitiativeMember.role_ref).selectinload(
                    InitiativeRoleModel.permissions
                ),
            ),
            selectinload(Document.grants).selectinload(ResourceGrant.role),
            selectinload(Document.property_values).selectinload(
                DocumentPropertyValue.property_definition
            ),
            selectinload(Document.property_values).selectinload(
                DocumentPropertyValue.value_user
            ),
        )
    )
    if populate_existing:
        # Force SA to refresh attributes on any Document already in the
        # session's identity map. Needed after commits that mutate
        # collections (e.g. property_values replace-all) since
        # expire_on_commit=False otherwise keeps stale relationships.
        statement = statement.execution_options(populate_existing=True)
    result = await session.exec(statement)
    document = result.one_or_none()
    if document:
        await tags_service.annotate_tags(session, [document])
        await annotate_comment_counts(session, [document])
    return document


async def get_document_for_export(
    session: AsyncSession,
    current_user,
    guild_id: int,
    *,
    document_id: int,
) -> Document:
    """The document-export adapter's seam: fetch + authorize in one place so
    the rule holds on the worker's render-time replay too. READ access
    suffices — exporting is a formatted read, unlike the project backup
    (which requires write). The guild role is resolved here rather than taken
    from a request context, so the seam works transport-free."""
    from fastapi import HTTPException, status as http_status

    from app.services import permissions as permissions_service

    document = await get_document(session, document_id=document_id, guild_id=guild_id)
    if document is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=DocumentMessages.NOT_FOUND,
        )
    permissions_service.require_document_access(
        document,
        current_user,
        access="read",
    )
    return document


async def list_document_ids_for_export(
    session: AsyncSession,
    current_user,
    guild_id: int,
    *,
    initiative_ids: list[int],
) -> list[int]:
    """Ids of every document the user may export in the given initiatives —
    DAC-visible to the user (a request that reaches the whole guild sees all).
    Deterministic order for stable backup output."""
    from sqlmodel import select

    if not initiative_ids:
        return []
    conditions = [
        Document.initiative_id.in_(initiative_ids),
    ]
    statement = select(Document.id).where(*conditions).order_by(Document.id.asc())
    return list(await session.exec(statement))


async def get_document_for_grants(
    session: AsyncSession, document_id: int
) -> Document | None:
    """Load a document with just the relationships the grant flow needs — its
    ``grants`` (owner resolution) and ``initiative.memberships`` (authorization).
    RLS scopes the row to the request's guild, so no explicit guild filter (mirrors
    the queue/counter grant loaders). Uniform ``(session, id)`` shape so
    ``resource_access`` can register it like the others."""
    statement = (
        select(Document)
        .where(Document.id == document_id)
        .options(
            selectinload(Document.initiative)
            .selectinload(Initiative.memberships)
            .options(
                selectinload(InitiativeMember.user),
                selectinload(InitiativeMember.role_ref).selectinload(
                    InitiativeRoleModel.permissions
                ),
            ),
            selectinload(Document.grants).selectinload(ResourceGrant.role),
        )
    )
    return (await session.exec(statement)).one_or_none()


async def duplicate_document(
    session: AsyncSession,
    *,
    source: Document,
    target_initiative_id: int,
    name: str,
    user_id: int,
    guild_id: int | None = None,
) -> Document:
    content_copy = normalize_document_content(
        deepcopy(source.content),
        document_type=source.document_type,
    )
    content_uploads = attachments_service.extract_upload_urls(content_copy)
    # Enforce the guild's storage quota BEFORE copying any bytes — a rejected
    # clone must not leave orphaned blobs on storage. Size it from the source
    # blobs it will duplicate (a copy is the same size as its source).
    effective_guild_id = guild_id or source.guild_id
    if effective_guild_id is not None:
        clone_source_urls = list(content_uploads)
        if source.featured_image_url:
            clone_source_urls.append(source.featured_image_url)
        incoming = await attachments_service.get_upload_bytes_for_urls(
            session, clone_source_urls
        )
        if incoming:
            await attachments_service.enforce_storage_quota(
                session,
                guild_id=effective_guild_id,
                incoming_bytes=incoming,
            )
    replacements = attachments_service.duplicate_uploads(content_uploads)
    if replacements:
        content_copy = attachments_service.replace_upload_urls(
            content_copy, replacements
        )

    featured_image_url = attachments_service.duplicate_upload(source.featured_image_url)

    # Track any newly created files in the uploads table for guild-scoped access control
    if effective_guild_id is not None:
        upload_dir = Path(settings.UPLOADS_DIR)
        new_upload_records: list[Upload] = []
        new_urls = list(replacements.values())
        # Map each new blob back to its source so we can carry the source's
        # content_type/content_hash onto the copy (it is byte-identical).
        new_to_source = {new: old for old, new in replacements.items()}
        if featured_image_url and featured_image_url != source.featured_image_url:
            new_urls.append(featured_image_url)
            if source.featured_image_url:
                new_to_source[featured_image_url] = source.featured_image_url
        source_meta = await attachments_service.get_upload_metadata_for_urls(
            session, list(new_to_source.values())
        )
        for new_url in new_urls:
            fname = new_url.split("/")[-1]
            if fname:
                source_url = new_to_source.get(new_url)
                source_fname = source_url.split("/")[-1] if source_url else None
                content_type, content_hash = (
                    source_meta.get(source_fname, (None, None))
                    if source_fname
                    else (None, None)
                )
                fpath = upload_dir / fname
                new_upload_records.append(
                    Upload(
                        filename=fname,
                        guild_id=effective_guild_id,
                        created_by=user_id,
                        size_bytes=fpath.stat().st_size if fpath.exists() else 0,
                        content_type=content_type,
                        content_hash=content_hash,
                    )
                )
        if new_upload_records:
            session.add_all(new_upload_records)

    duplicated = Document(
        name=name,
        initiative_id=target_initiative_id,
        guild_id=guild_id or source.guild_id,
        document_type=source.document_type,
        content=content_copy,
        created_by=user_id,
        featured_image_url=featured_image_url,
        is_template=False,
    )
    session.add(duplicated)
    await session.flush()

    # Add owner permission for the user creating the duplicate
    owner_permission = ResourceGrant(
        resource_type="document",
        resource_id=duplicated.id,
        user_id=user_id,
        role_id=None,
        level=ResourceAccessLevel.owner,
        guild_id=guild_id or source.guild_id,
        initiative_id=duplicated.initiative_id,
    )
    session.add(owner_permission)

    # Copy tags from source document (active only)
    await tags_service.copy_entity_tags(
        session,
        tags_service.TOOL_TAG_LINKS[Tool.document],
        source_id=source.id,
        target_id=duplicated.id,
    )

    # Copy property values ONLY when the target initiative matches the
    # source's — definitions are initiative-scoped, so cross-initiative
    # copies would produce orphaned values the target can't resolve.
    if target_initiative_id == source.initiative_id:
        source_value_stmt = select(DocumentPropertyValue).where(
            DocumentPropertyValue.document_id == source.id
        )
        source_values_result = await session.exec(source_value_stmt)
        source_values = source_values_result.all()
        if source_values:
            session.add_all(
                [
                    DocumentPropertyValue(
                        document_id=duplicated.id,
                        property_id=row.property_id,
                        value_text=row.value_text,
                        value_number=row.value_number,
                        value_boolean=row.value_boolean,
                        value_date=row.value_date,
                        value_datetime=row.value_datetime,
                        value_user_id=row.value_user_id,
                        value_json=deepcopy(row.value_json)
                        if row.value_json is not None
                        else None,
                    )
                    for row in source_values
                ]
            )

    await session.commit()
    return duplicated


async def annotate_comment_counts(
    session: AsyncSession, documents: Sequence[Document]
) -> None:
    document_ids = [document.id for document in documents if document.id is not None]
    if not document_ids:
        return
    stmt = (
        select(Comment.document_id, func.count(Comment.id))
        .where(Comment.document_id.in_(tuple(document_ids)))
        .group_by(Comment.document_id)
    )
    result = await session.exec(stmt)
    counts = dict(result.all())
    for document in documents:
        object.__setattr__(document, "comment_count", counts.get(document.id, 0))


async def unresolve_wikilinks_to_document(
    session: AsyncSession,
    *,
    deleted_document_id: int,
) -> None:
    """Blank every ``[[ ]]`` pointing at a document that is being hard-purged.

    The link nodes stay and render as unresolved, which is what the editor shows
    for a link whose target was never picked. Their ``references`` edges go with
    the document itself, through the purge path's own sweep.

    Called by ``hard_purge_entity`` before the DELETEs are issued, while the
    edges naming the document are still there to find the documents that carry
    those links. Trashed ones are included — a document restored after the purge
    must not come back with a dangling link.
    """
    from app.services.tenant import content_references

    linking_documents = await content_references.referencing_documents(
        session, deleted_document_id
    )

    # Documents whose in-memory collaboration room has to be retired, so
    # persist_room cannot write the pre-repair content back over this.
    affected_doc_ids: list[int] = []

    for doc in linking_documents:
        if doc.content and isinstance(doc.content, dict):
            updated_content = deepcopy(doc.content)
            if unresolve_wikilinks_to(updated_content, deleted_document_id):
                doc.content = updated_content
                # Yjs state takes precedence over content on load; clear it so
                # collaboration bootstraps from the repaired content.
                doc.yjs_state = None
                flag_modified(doc, "content")
                session.add(doc)
                affected_doc_ids.append(doc.id)

    await session.flush()

    # Invalidate any in-memory collaboration rooms for affected documents
    # This prevents persist_room from overwriting our changes when users disconnect
    # Note: If a room has active collaborators, they'll have stale wikilinks until reload
    # Rooms are keyed by (guild, document), and the documents above were read
    # through this session, so the guild it is routed to is theirs. An unrouted
    # session reaches no guild schema and so has no room to invalidate.
    guild_id = routed_guild_id(session)
    if guild_id is not None:
        for doc_id in affected_doc_ids:
            await collaboration_manager.invalidate_room_if_empty(guild_id, doc_id)
