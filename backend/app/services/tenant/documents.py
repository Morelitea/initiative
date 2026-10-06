from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import selectinload, undefer
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.search import SearchEntityType
from app.models.tenant.document import Document, DocumentType
from app.models.tenant.resource_grant import ResourceGrant
from app.core.references import unresolve_wikilinks_to
from app.core.messages import DocumentMessages
from app.services.tenant import attachments as attachments_service
from app.services.tenant import body_states
from app.services.tenant import comments as comments_service
from app.services.tenant import content_references
from app.services.tenant import file_versions
from app.services.tenant import ownership as ownership_service
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant.collaboration import collaboration_manager, written_into
from app.db.session import routed_guild_id

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext


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


def list_loader_options() -> list:
    """Eager-load what a document *list* row needs: its initiative, the level
    the request holds on it, a link document's address, its sharing with the
    grant holders (the owner is reported by name), and the property values its
    card shows. Not the body, which a list does not show."""
    return [
        selectinload(Document.initiative),
        undefer(Document.actions),
        undefer(Document.smart_link_url),
        selectinload(Document.grants).selectinload(ResourceGrant.user),
    ]


async def get_document_hydrated(
    session: AsyncSession, document_id: int, *, populate_existing: bool = False
) -> Document | None:
    """Load a document with everything a serialized ``DocumentRead`` or an
    export reads: the list loader's eager loads and the body, plus the tags,
    comment count and owning plug-in a response carries.
    :func:`get_document_for_grants` carries the list loads alone, which is what
    the access decision needs. Uniform ``(session, id)`` shape, the one ``resource_access``
    registers a loader by.
    """
    statement = (
        select(Document)
        .where(Document.id == document_id)
        .options(*list_loader_options(), undefer(Document.content))
    )
    if populate_existing:
        # Refresh a document already in the identity map, for a re-read after a
        # commit (expire_on_commit=False otherwise keeps stale collections).
        statement = statement.execution_options(populate_existing=True)
    document = (await session.exec(statement)).one_or_none()
    if document:
        await tags_service.annotate_tags(session, [document])
        await properties_service.annotate_properties(session, [document])
        await comments_service.annotate_comment_counts(
            session, [document], column="document_id"
        )
        await ownership_service.annotate_owner_plugins(session, [document])
    return document


async def get_document_for_grants(
    session: AsyncSession, document_id: int
) -> Document | None:
    """Load a document as a list row carries it — its ``grants`` (owner
    resolution) and the level the request holds on it, without the body the
    grant flow never reads. RLS scopes the row to the request's guild, so no
    explicit guild filter. Uniform ``(session, id)`` shape so
    ``resource_access`` can register it like the others."""
    statement = (
        select(Document)
        .where(Document.id == document_id)
        .options(*list_loader_options())
    )
    return (await session.exec(statement)).one_or_none()


async def copy_contents(
    session: AsyncSession, source: Document, copy: Document, actor: ActorContext
) -> list[Any]:
    """Finish ``copy``, a duplicate of ``source`` already shared. Its pictures
    and stored file are copied rather than shared, so each document's can be
    released on its own; a file document's copy starts again at version 1.
    Makes no rows inside it."""
    content = normalize_document_content(copy.content, document_type=copy.document_type)
    current = source.current_version
    file_url = current.file_url if current is not None else None
    copies = await attachments_service.copy_uploads(
        session,
        [
            *attachments_service.extract_upload_urls(content),
            copy.featured_image_url,
            file_url,
        ],
        guild_id=actor.guild_id,
        created_by=actor.user_id,
        initiative_id=copy.initiative_id,
    )

    def copied(url: str | None) -> str | None:
        return copies.get(attachments_service.normalize_upload_url(url) or "", url)

    copy.content = attachments_service.replace_upload_urls(content, copies)
    copy.featured_image_url = copied(copy.featured_image_url)
    if current is not None:
        # A plug-in is never an author: its copy names the file's uploader.
        file_versions.copy_version(
            session,
            current,
            copy,
            file_url=copied(file_url),
            created_by=actor.user_id or current.created_by,
        )
    return []


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

    linking_documents = await content_references.referencing_documents(
        session, deleted_document_id
    )

    # Documents whose in-memory collaboration room has to be retired, so
    # a room's save cannot write the pre-repair content back over this.
    affected_doc_ids: list[int] = []

    for doc in linking_documents:
        if doc.content and isinstance(doc.content, dict):
            updated_content = deepcopy(doc.content)
            if unresolve_wikilinks_to(updated_content, deleted_document_id):
                doc.content = updated_content
                # A session opens on the Yjs state, so the repair is written
                # into it too.
                await session.refresh(doc, ["yjs_state"])
                doc.yjs_state = await written_into(
                    body_states.LEXICAL, doc.yjs_state, updated_content
                )
                flag_modified(doc, "content")
                session.add(doc)
                affected_doc_ids.append(doc.id)

    await session.flush()

    # Invalidate any in-memory collaboration rooms for affected documents
    # This prevents a room's save from overwriting our changes when users disconnect
    # Note: If a room has active collaborators, they'll have stale wikilinks until reload
    # Rooms are keyed by (guild, document), and the documents above were read
    # through this session, so the guild it is routed to is theirs. An unrouted
    # session reaches no guild schema and so has no room to invalidate.
    guild_id = routed_guild_id(session)
    if guild_id is not None:
        for doc_id in affected_doc_ids:
            await collaboration_manager.invalidate_room_if_empty(
                guild_id, SearchEntityType.document.value, doc_id
            )
