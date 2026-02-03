from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.comment import Comment
from app.models.document import Document, DocumentPermission, DocumentPermissionLevel, ProjectDocument
from app.models.initiative import Initiative, InitiativeMember, InitiativeRole, InitiativeRoleModel
from app.models.project import Project
from app.services import attachments as attachments_service


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
