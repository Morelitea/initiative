from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.document import Document, ProjectDocument
from app.models.initiative import Initiative, InitiativeMember
from app.models.project import Project


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
        )
    )
    result = await session.exec(statement)
    return result.one_or_none()


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
