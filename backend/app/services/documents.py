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
from app.models.initiative import Initiative, InitiativeMember
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
            selectinload(Document.initiative).selectinload(Initiative.memberships).selectinload(InitiativeMember.user),
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
        content=content_copy,
        created_by_id=user_id,
        updated_by_id=user_id,
        featured_image_url=featured_image_url,
        is_template=False,
    )
    session.add(duplicated)
    await session.commit()
    await session.refresh(duplicated)
    return duplicated


async def set_document_write_permissions(
    session: AsyncSession,
    *,
    document: Document,
    write_member_ids: set[int],
) -> None:
    existing_permissions = {
        permission.user_id: permission for permission in (document.permissions or [])
    }
    desired = set(write_member_ids)

    # Remove permissions not desired
    for user_id, permission in list(existing_permissions.items()):
        if user_id not in desired:
            await session.delete(permission)

    # Add new permissions
    for user_id in desired - set(existing_permissions):
        new_permission = DocumentPermission(
            document_id=document.id,
            user_id=user_id,
            level=DocumentPermissionLevel.write,
        )
        session.add(new_permission)
        document.permissions = (document.permissions or []) + [new_permission]

    # Trim relationship cache to match desired set
    if document.permissions:
        document.permissions = [
            permission for permission in document.permissions if permission.user_id in desired
        ]

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
