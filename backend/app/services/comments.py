from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
from typing import Optional, cast

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.comment import Comment
from app.models.document import Document, DocumentPermission
from app.models.guild import GuildRole
from app.models.initiative import Initiative, InitiativeMember
from app.models.project import Project, ProjectPermission
from app.models.task import Task
from app.models.user import User
from app.services import documents as documents_service
from app.services import initiatives as initiatives_service


class CommentError(Exception):
    """Base error for comment operations."""


class CommentNotFoundError(CommentError):
    """Raised when a linked resource cannot be found."""


class CommentPermissionError(CommentError):
    """Raised when the user lacks permission to comment."""


class CommentValidationError(CommentError):
    """Raised when the payload is inconsistent."""


@dataclass
class _TaskContext:
    task: Task
    project: Project
    initiative: Initiative


async def _get_task_context(
    session: AsyncSession,
    *,
    task_id: int,
    guild_id: int,
) -> Optional[_TaskContext]:
    stmt = (
        select(Task, Project, Initiative)
        .join(Project, Project.id == Task.project_id)
        .join(Initiative, Initiative.id == Project.initiative_id)
        .where(
            Task.id == task_id,
            Initiative.guild_id == guild_id,
        )
    )
    result = await session.exec(stmt)
    row = result.one_or_none()
    if not row:
        return None
    task, project, initiative = row
    return _TaskContext(task=task, project=project, initiative=initiative)


async def _is_initiative_member(
    session: AsyncSession,
    *,
    initiative_id: int,
    user_id: int,
) -> bool:
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == user_id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    return membership is not None


async def _has_project_permission(
    session: AsyncSession,
    *,
    project_id: int,
    user_id: int,
) -> bool:
    stmt = select(ProjectPermission).where(
        ProjectPermission.project_id == project_id,
        ProjectPermission.user_id == user_id,
    )
    result = await session.exec(stmt)
    permission = result.one_or_none()
    return permission is not None


async def _ensure_task_access(
    session: AsyncSession,
    *,
    project: Project,
    initiative: Initiative,
    user: User,
    guild_role: GuildRole,
) -> None:
    if guild_role == GuildRole.admin:
        return
    if project.owner_id == user.id:
        return
    if await _is_initiative_member(session, initiative_id=initiative.id, user_id=user.id):
        return
    if await _has_project_permission(session, project_id=project.id, user_id=user.id):
        return
    raise CommentPermissionError("Not authorized to comment on this task")


async def _ensure_document_access(
    session: AsyncSession,
    *,
    document: Document,
    user: User,
    guild_role: GuildRole,
) -> None:
    if guild_role == GuildRole.admin:
        return
    if await _is_initiative_member(session, initiative_id=document.initiative_id, user_id=user.id):
        return
    permissions = getattr(document, "permissions", None)
    if permissions is None:
        stmt = select(DocumentPermission).where(DocumentPermission.document_id == document.id)
        result = await session.exec(stmt)
        permissions = result.all()
    for permission in permissions or []:
        if permission.user_id == user.id:
            return
    raise CommentPermissionError("Not authorized to comment on this document")


async def _get_comment(
    session: AsyncSession,
    *,
    comment_id: int,
) -> Optional[Comment]:
    stmt = select(Comment).where(Comment.id == comment_id)
    result = await session.exec(stmt)
    return result.one_or_none()


async def create_comment(
    session: AsyncSession,
    *,
    author: User,
    guild_id: int,
    guild_role: GuildRole,
    content: str,
    task_id: Optional[int] = None,
    document_id: Optional[int] = None,
    parent_comment_id: Optional[int] = None,
) -> Comment:
    parent_comment = None
    if parent_comment_id is not None:
        parent_comment = await _get_comment(session, comment_id=parent_comment_id)
        if not parent_comment:
            raise CommentNotFoundError("Parent comment not found")

    if task_id is not None:
        context = await _get_task_context(session, task_id=task_id, guild_id=guild_id)
        if not context:
            raise CommentNotFoundError("Task not found")
        await _ensure_task_access(
            session,
            project=context.project,
            initiative=context.initiative,
            user=author,
            guild_role=guild_role,
        )
        if parent_comment and parent_comment.task_id != context.task.id:
            raise CommentValidationError("Parent comment belongs to a different task")
        comment = Comment(
            content=content,
            author_id=cast(int, author.id),
            task_id=context.task.id,
            parent_comment_id=parent_comment_id,
        )
    else:
        if document_id is None:
            raise CommentValidationError("Document id is required")
        document = await documents_service.get_document(
            session,
            document_id=document_id,
            guild_id=guild_id,
        )
        if not document:
            raise CommentNotFoundError("Document not found")
        await _ensure_document_access(
            session,
            document=document,
            user=author,
            guild_role=guild_role,
        )
        if parent_comment and parent_comment.document_id != document.id:
            raise CommentValidationError("Parent comment belongs to a different document")
        comment = Comment(
            content=content,
            author_id=cast(int, author.id),
            document_id=document.id,
            parent_comment_id=parent_comment_id,
        )

    session.add(comment)
    await session.flush()
    await session.refresh(comment, attribute_names=["author"])
    return comment


async def list_comments(
    session: AsyncSession,
    *,
    user: User,
    guild_id: int,
    guild_role: GuildRole,
    task_id: Optional[int] = None,
    document_id: Optional[int] = None,
) -> Sequence[Comment]:
    has_task = task_id is not None
    has_document = document_id is not None
    if has_task == has_document:
        raise CommentValidationError("Provide exactly one of task_id or document_id")

    if has_task:
        context = await _get_task_context(session, task_id=task_id, guild_id=guild_id)
        if not context:
            raise CommentNotFoundError("Task not found")
        await _ensure_task_access(
            session,
            project=context.project,
            initiative=context.initiative,
            user=user,
            guild_role=guild_role,
        )
        stmt = (
            select(Comment)
            .where(Comment.task_id == context.task.id)
            .order_by(Comment.created_at.asc(), Comment.id.asc())
            .options(selectinload(Comment.author))
        )
    else:
        document = await documents_service.get_document(
            session,
            document_id=document_id,
            guild_id=guild_id,
        )
        if not document:
            raise CommentNotFoundError("Document not found")
        await _ensure_document_access(
            session,
            document=document,
            user=user,
            guild_role=guild_role,
        )
        stmt = (
            select(Comment)
            .where(Comment.document_id == document.id)
            .order_by(Comment.created_at.asc(), Comment.id.asc())
            .options(selectinload(Comment.author))
        )

    result = await session.exec(stmt)
    return result.all()


async def delete_comment(
    session: AsyncSession,
    *,
    comment_id: int,
    user: User,
    guild_id: int,
    guild_role: GuildRole,
) -> Comment:
    comment = await _get_comment(session, comment_id=comment_id)
    if not comment:
        raise CommentNotFoundError("Comment not found")

    initiative_id: int | None = None

    if comment.task_id is not None:
        context = await _get_task_context(session, task_id=comment.task_id, guild_id=guild_id)
        if not context:
            raise CommentNotFoundError("Comment not found")
        initiative_id = context.initiative.id
        await _ensure_task_access(
            session,
            project=context.project,
            initiative=context.initiative,
            user=user,
            guild_role=guild_role,
        )
    elif comment.document_id is not None:
        document = await documents_service.get_document(
            session,
            document_id=comment.document_id,
            guild_id=guild_id,
        )
        if not document:
            raise CommentNotFoundError("Comment not found")
        initiative_id = document.initiative_id
        await _ensure_document_access(
            session,
            document=document,
            user=user,
            guild_role=guild_role,
        )
    else:
        raise CommentValidationError("Comment is not linked to a task or document")

    is_author = comment.author_id == user.id
    is_guild_admin = guild_role == GuildRole.admin
    is_initiative_manager = False
    if not is_author and not is_guild_admin and initiative_id is not None:
        is_initiative_manager = await initiatives_service.is_initiative_manager(
            session,
            initiative_id=initiative_id,
            user=user,
        )

    if not (is_author or is_guild_admin or is_initiative_manager):
        raise CommentPermissionError("You can only delete your own comments")

    await session.delete(comment)
    return comment
