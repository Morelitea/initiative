from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.comment import Comment
from app.models.document import Document, DocumentLink, DocumentPermission, DocumentPermissionLevel, ProjectDocument
from app.models.initiative import Initiative, InitiativeMember, InitiativeRole, InitiativeRoleModel
from app.models.project import Project
from app.services import attachments as attachments_service
from app.services.collaboration import collaboration_manager


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


def normalize_document_content(payload: dict[str, Any] | None) -> dict[str, Any]:
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
                selectinload(InitiativeMember.role_ref).selectinload(InitiativeRoleModel.permissions),
            ),
            selectinload(Document.project_links).selectinload(ProjectDocument.project),
            selectinload(Document.permissions),
        )
    )
    result = await session.exec(statement)
    document = result.one_or_none()
    if document:
        await annotate_comment_counts(session, [document])
    return document


async def attach_document_to_project(
    session: AsyncSession,
    *,
    document: Document,
    project: Project,
    user_id: int,
) -> ProjectDocument:
    stmt = select(ProjectDocument).where(
        ProjectDocument.project_id == project.id,
        ProjectDocument.document_id == document.id,
    )
    result = await session.exec(stmt)
    link = result.one_or_none()
    if link:
        return link

    link = ProjectDocument(
        project_id=project.id,
        document_id=document.id,
        attached_by_id=user_id,
        attached_at=datetime.now(timezone.utc),
    )
    session.add(link)
    await session.commit()
    await session.refresh(link)
    return link


async def detach_document_from_project(
    session: AsyncSession,
    *,
    document_id: int,
    project_id: int,
) -> None:
    stmt = select(ProjectDocument).where(
        ProjectDocument.project_id == project_id,
        ProjectDocument.document_id == document_id,
    )
    result = await session.exec(stmt)
    link = result.one_or_none()
    if link:
        await session.delete(link)
        await session.commit()


async def duplicate_document(
    session: AsyncSession,
    *,
    source: Document,
    target_initiative_id: int,
    title: str,
    user_id: int,
    guild_id: int | None = None,
) -> Document:
    content_copy = normalize_document_content(deepcopy(source.content))
    content_uploads = attachments_service.extract_upload_urls(content_copy)
    replacements = attachments_service.duplicate_uploads(content_uploads)
    if replacements:
        content_copy = attachments_service.replace_upload_urls(content_copy, replacements)

    featured_image_url = attachments_service.duplicate_upload(source.featured_image_url)

    duplicated = Document(
        title=title,
        initiative_id=target_initiative_id,
        guild_id=guild_id or source.guild_id,
        content=content_copy,
        created_by_id=user_id,
        updated_by_id=user_id,
        featured_image_url=featured_image_url,
        is_template=False,
    )
    session.add(duplicated)
    await session.flush()

    # Add owner permission for the user creating the duplicate
    owner_permission = DocumentPermission(
        document_id=duplicated.id,
        user_id=user_id,
        level=DocumentPermissionLevel.owner,
        guild_id=guild_id or source.guild_id,
    )
    session.add(owner_permission)
    await session.commit()
    await session.refresh(duplicated)
    return duplicated


async def handle_owner_removal(
    session: AsyncSession,
    *,
    initiative_id: int,
    user_id: int,
) -> None:
    """Handle documents when their owner is removed from an initiative.

    When a user is removed from an initiative, any documents they own become
    "orphaned". This function removes the owner's permission and grants owner
    access to all initiative PMs so they can fully manage the document.
    """
    # Find documents where user is owner
    stmt = (
        select(Document)
        .join(DocumentPermission)
        .where(
            Document.initiative_id == initiative_id,
            DocumentPermission.user_id == user_id,
            DocumentPermission.level == DocumentPermissionLevel.owner,
        )
        .options(selectinload(Document.permissions))
    )
    result = await session.exec(stmt)
    documents = result.all()

    if not documents:
        return

    # Get all initiative PMs
    pm_result = await session.exec(
        select(InitiativeMember).where(
            InitiativeMember.initiative_id == initiative_id,
            InitiativeMember.role == InitiativeRole.project_manager,
        )
    )
    pm_user_ids = {pm.user_id for pm in pm_result.all()}

    for doc in documents:
        # Remove owner's permission
        owner_permission = next(
            (p for p in doc.permissions if p.user_id == user_id and p.level == DocumentPermissionLevel.owner),
            None,
        )
        if owner_permission:
            await session.delete(owner_permission)

        # Grant owner access to all PMs who don't already have permission
        # so they can manage (including delete) the orphaned document
        existing_user_ids = {p.user_id for p in doc.permissions}
        for pm_user_id in pm_user_ids:
            if pm_user_id not in existing_user_ids and pm_user_id != user_id:
                pm_permission = DocumentPermission(
                    document_id=doc.id,
                    user_id=pm_user_id,
                    level=DocumentPermissionLevel.owner,
                    guild_id=doc.guild_id,
                )
                session.add(pm_permission)

    await session.flush()


async def annotate_comment_counts(session: AsyncSession, documents: Sequence[Document]) -> None:
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


def extract_wikilink_document_ids(content: dict[str, Any] | None) -> set[int]:
    """Extract all target document IDs from WikilinkNodes in the content.

    Recursively walks the Lexical state tree looking for nodes with
    type="wikilink" and a valid documentId.
    """
    if not isinstance(content, dict):
        return set()

    document_ids: set[int] = set()

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        # Check if this is a wikilink node
        if node.get("type") == "wikilink":
            doc_id = node.get("documentId")
            if isinstance(doc_id, int) and doc_id > 0:
                document_ids.add(doc_id)
        # Recursively process children
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                walk(child)

    # Start from root
    root = content.get("root")
    if isinstance(root, dict):
        walk(root)

    return document_ids


def unresolve_invalid_wikilinks(content: dict[str, Any], valid_doc_ids: set[int]) -> bool:
    """Set documentId to null for wikilinks pointing to non-existent documents.

    This fixes stale wikilinks that reference deleted documents.
    Returns True if any changes were made.
    """
    changed = False

    def walk(node: Any) -> None:
        nonlocal changed
        if not isinstance(node, dict):
            return
        if node.get("type") == "wikilink":
            doc_id = node.get("documentId")
            if isinstance(doc_id, int) and doc_id > 0 and doc_id not in valid_doc_ids:
                node["documentId"] = None
                changed = True
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                walk(child)

    root = content.get("root")
    if isinstance(root, dict):
        walk(root)

    return changed


async def sync_document_links(
    session: AsyncSession,
    *,
    document_id: int,
    content: dict[str, Any] | None,
    guild_id: int | None = None,
    fix_content: bool = False,
) -> dict[str, Any] | None:
    """Sync the document_links table based on WikilinkNodes in the content.

    This extracts all wikilink document IDs from the content and updates
    the document_links table to reflect the current state:
    - Adds new links (only to documents that exist)
    - Removes links that no longer exist in the content

    If fix_content=True, also unresolves any wikilinks pointing to deleted
    documents and returns the fixed content. Otherwise returns None.

    Called on document save to keep backlinks up to date.
    """
    if not content or not isinstance(content, dict):
        return None

    # Extract current wikilink targets
    current_target_ids = extract_wikilink_document_ids(content)

    # Validate which target documents actually exist
    # This prevents FK violations when wikilinks point to deleted documents
    if current_target_ids:
        valid_docs_stmt = select(Document.id).where(Document.id.in_(current_target_ids))
        valid_docs_result = await session.exec(valid_docs_stmt)
        valid_target_ids = set(valid_docs_result.all())
    else:
        valid_target_ids = set()

    # Optionally fix stale wikilinks in the content
    fixed_content = None
    if fix_content and current_target_ids:
        invalid_ids = current_target_ids - valid_target_ids
        if invalid_ids:
            fixed_content = deepcopy(content)
            unresolve_invalid_wikilinks(fixed_content, valid_target_ids)

    # Get existing links from database
    stmt = select(DocumentLink).where(DocumentLink.source_document_id == document_id)
    result = await session.exec(stmt)
    existing_links = result.all()
    existing_target_ids = {link.target_document_id for link in existing_links}

    # Determine adds and removes (only add links to valid documents)
    to_add = valid_target_ids - existing_target_ids
    to_remove = existing_target_ids - valid_target_ids

    # Remove old links (including links to documents that no longer exist)
    for link in existing_links:
        if link.target_document_id in to_remove:
            await session.delete(link)

    # Add new links
    for target_id in to_add:
        new_link = DocumentLink(
            source_document_id=document_id,
            target_document_id=target_id,
            guild_id=guild_id,
        )
        session.add(new_link)

    # Flush but don't commit - let caller handle transaction
    if to_add or to_remove:
        await session.flush()

    return fixed_content


async def get_backlinks(
    session: AsyncSession,
    *,
    document_id: int,
    user_id: int,
) -> list[Document]:
    """Get documents that link to the specified document.

    Only returns documents the user has permission to access.
    """
    # Subquery: documents where user has explicit permission
    has_permission_subq = (
        select(DocumentPermission.document_id)
        .where(DocumentPermission.user_id == user_id)
        .scalar_subquery()
    )

    stmt = (
        select(Document)
        .join(DocumentLink, DocumentLink.source_document_id == Document.id)
        .where(
            DocumentLink.target_document_id == document_id,
            Document.id.in_(has_permission_subq),
        )
        .order_by(Document.updated_at.desc())
    )

    result = await session.exec(stmt)
    return list(result.all())


def _unresolve_wikilinks_in_content(content: dict[str, Any], target_document_id: int) -> bool:
    """Set documentId to null for wikilinks pointing to the target document.

    Returns True if any changes were made.
    """
    changed = False

    def walk(node: Any) -> None:
        nonlocal changed
        if not isinstance(node, dict):
            return
        # Check if this is a wikilink node pointing to the target
        if node.get("type") == "wikilink" and node.get("documentId") == target_document_id:
            node["documentId"] = None
            changed = True
        # Recursively process children
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                walk(child)

    root = content.get("root")
    if isinstance(root, dict):
        walk(root)

    return changed


async def unresolve_wikilinks_to_document(
    session: AsyncSession,
    *,
    deleted_document_id: int,
) -> None:
    """Unresolve all wikilinks pointing to a document that is being deleted.

    This updates the content of all documents that link to the deleted document,
    setting the wikilink's documentId to null so they appear as unresolved.
    Also removes the corresponding document_links entries and invalidates
    any in-memory collaboration rooms.

    Should be called before deleting a document.
    """
    # Find all documents that link to this document
    stmt = (
        select(Document)
        .join(DocumentLink, DocumentLink.source_document_id == Document.id)
        .where(DocumentLink.target_document_id == deleted_document_id)
    )
    result = await session.exec(stmt)
    linking_documents = list(result.all())

    # Track document IDs that need their collaboration rooms invalidated
    affected_doc_ids: list[int] = []

    # Update each document's content to unresolve the wikilinks
    for doc in linking_documents:
        if doc.content and isinstance(doc.content, dict):
            # Make a deep copy to avoid mutating the original
            updated_content = deepcopy(doc.content)
            if _unresolve_wikilinks_in_content(updated_content, deleted_document_id):
                doc.content = updated_content
                # Clear yjs_state so collaboration will bootstrap from updated content
                # This is necessary because yjs_state takes precedence when loading
                doc.yjs_state = None
                # Explicitly mark content as modified for SQLAlchemy to detect the change
                flag_modified(doc, "content")
                session.add(doc)
                affected_doc_ids.append(doc.id)

    # Delete the document_links entries pointing to this document
    links_stmt = select(DocumentLink).where(DocumentLink.target_document_id == deleted_document_id)
    links_result = await session.exec(links_stmt)
    for link in links_result.all():
        await session.delete(link)

    # Flush changes (caller will commit)
    await session.flush()

    # Invalidate any in-memory collaboration rooms for affected documents
    # This prevents persist_room from overwriting our changes when users disconnect
    # Note: If a room has active collaborators, they'll have stale wikilinks until reload
    for doc_id in affected_doc_ids:
        await collaboration_manager.invalidate_room_if_empty(doc_id)
