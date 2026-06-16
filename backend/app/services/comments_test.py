"""Tests for PAM-grant awareness in comment access checks.

A live grant lets a grantee read a guild's task/document comments (read) and,
for a read_write grant, post them — without any DAC permission row. A read-only
grant must NOT be able to post.
"""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.pam_context import set_active_grant
from app.models.document import Document
from app.services.comments import (
    CommentPermissionError,
    _ensure_document_access,
    _ensure_task_access,
)
from app.testing import create_guild, create_initiative, create_project, create_user


@pytest.mark.integration
async def test_ensure_task_access_honors_grant(session: AsyncSession):
    owner = await create_user(session, email="owner-cmt@example.com")
    grantee = await create_user(session, email="grantee-cmt@example.com")
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner)
    project = await create_project(session, init, owner, name="P")

    try:
        # No grant: a non-member is denied.
        set_active_grant(None, None)
        with pytest.raises(CommentPermissionError):
            await _ensure_task_access(
                session, project=project, user=grantee, access="read"
            )

        # Read grant: may read comments, but not post.
        set_active_grant(guild.id, "read")
        await _ensure_task_access(session, project=project, user=grantee, access="read")
        with pytest.raises(CommentPermissionError):
            await _ensure_task_access(
                session, project=project, user=grantee, access="write"
            )

        # Read-write grant: may post.
        set_active_grant(guild.id, "read_write")
        await _ensure_task_access(
            session, project=project, user=grantee, access="write"
        )

        # A grant for a different guild doesn't apply.
        set_active_grant(guild.id + 999, "read_write")
        with pytest.raises(CommentPermissionError):
            await _ensure_task_access(
                session, project=project, user=grantee, access="read"
            )
    finally:
        set_active_grant(None, None)


@pytest.mark.integration
async def test_ensure_document_access_honors_grant(session: AsyncSession):
    owner = await create_user(session, email="owner-cmt2@example.com")
    grantee = await create_user(session, email="grantee-cmt2@example.com")
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner)
    document = Document(
        guild_id=guild.id,
        initiative_id=init.id,
        title="Doc",
        content={},
        created_by_id=owner.id,
        updated_by_id=owner.id,
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)
    # Eager-load the relationship the DAC fallback reads (the real endpoint
    # loads it via selectinload); avoids a lazy load in the async test.
    await session.refresh(document, ["permissions"])

    try:
        set_active_grant(guild.id, "read")
        await _ensure_document_access(
            session, document=document, user=grantee, access="read"
        )
        with pytest.raises(CommentPermissionError):
            await _ensure_document_access(
                session, document=document, user=grantee, access="write"
            )

        set_active_grant(guild.id, "read_write")
        await _ensure_document_access(
            session, document=document, user=grantee, access="write"
        )
    finally:
        set_active_grant(None, None)
