"""Tests for PAM-grant awareness in comment access checks.

A live grant lets a grantee read a guild's comment threads (read) and, for a
read_write grant, post to them — without any DAC permission row. A read-only
grant must NOT be able to post.
"""

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.pam_context import set_active_grant
from app.core.tools import Tool
from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole
from app.models.tenant.document import Document
from app.services.tenant.comments import (
    CommentPermissionError,
    _ensure_parent_access,
    _load_parent,
)
from app.testing.factories import TOOL_FACTORIES
from app.testing import (
    create_comment,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_task,
    create_user,
)


@pytest.mark.integration
async def test_task_comment_access_honors_grant(session: AsyncSession, role_session):
    owner = await create_user(session, email="owner-cmt@example.com")
    grantee = await create_user(session, email="grantee-cmt@example.com")
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner)
    project = await create_project(session, init, owner, name="P")
    task = await create_task(session, project)

    ctx = await _load_parent(
        session, column="task_id", entity_id=task.id, guild_id=guild.id
    )
    assert ctx is not None

    # Asked on a session that reaches Postgres as the app does. The sharing
    # decision is the parent table's own policy now — selecting the id IS the
    # question — so a session that bypasses row-level security cannot answer it,
    # and would say yes to everything below.
    reader = await role_session("app_user")
    await set_rls_context(reader, user_id=grantee.id, guild_id=guild.id)

    try:
        # No grant: a non-member is denied.
        set_active_grant(None, None)
        with pytest.raises(CommentPermissionError):
            await _ensure_parent_access(reader, ctx, user=grantee, access="read")

        # Read grant: may read comments.
        set_active_grant(guild.id, "read")
        await _ensure_parent_access(reader, ctx, user=grantee, access="read")

        # Read-write grant: may post.
        set_active_grant(guild.id, "read_write")
        await _ensure_parent_access(reader, ctx, user=grantee, access="write")

        # A grant for a different guild doesn't apply.
        set_active_grant(guild.id + 999, "read_write")
        with pytest.raises(CommentPermissionError):
            await _ensure_parent_access(reader, ctx, user=grantee, access="read")
    finally:
        set_active_grant(None, None)


@pytest.mark.integration
async def test_document_comment_access_honors_grant(
    session: AsyncSession, role_session
):
    """The other branch of the parent check: a tool entity answers for itself,
    where a task answers through its project."""
    owner = await create_user(session, email="owner-cmt2@example.com")
    grantee = await create_user(session, email="grantee-cmt2@example.com")
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner)
    document = Document(
        guild_id=guild.id,
        initiative_id=init.id,
        name="Doc",
        content={},
        created_by=owner.id,
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)

    ctx = await _load_parent(
        session, column="document_id", entity_id=document.id, guild_id=guild.id
    )
    assert ctx is not None

    reader = await role_session("app_user")
    await set_rls_context(reader, user_id=grantee.id, guild_id=guild.id)

    try:
        set_active_grant(None, None)
        with pytest.raises(CommentPermissionError):
            await _ensure_parent_access(reader, ctx, user=grantee, access="read")

        set_active_grant(guild.id, "read")
        await _ensure_parent_access(reader, ctx, user=grantee, access="read")

        set_active_grant(guild.id, "read_write")
        await _ensure_parent_access(reader, ctx, user=grantee, access="write")
    finally:
        set_active_grant(None, None)


@pytest.mark.integration
async def test_a_read_only_grant_cannot_post(session: AsyncSession, role_session):
    """The half of the rule the parent check no longer answers.

    Reaching a thread and adding to it are different questions, and only the
    first is "can this request see the parent". Posting is a write, and a
    read-only window is routed into the SELECT-only guild role — so the refusal
    is the insert's, and this is where it has to be asked.

    Under the real ``app_user`` login, like the RLS legs below: a session that
    reaches Postgres as a superuser would accept the insert whatever the
    window said.

    The assertion is on the outcome rather than on which layer produced it.
    Both are real refusals, and pinning the message would make this fail the
    day the grant layer changes without the rule changing.
    """
    owner = await create_user(session, email="owner-cmt-ro@example.com")
    support = await create_user(session, email="support-cmt-ro@example.com")
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner)
    project = await create_project(session, init, owner, name="P")
    task = await create_task(session, project)

    insert = text(
        "INSERT INTO comments (task_id, content, created_by, guild_id,"
        " created_at, updated_at)"
        " VALUES (:t, 'let me in', :u, :g, now(), now())"
    ).bindparams(t=task.id, u=support.id, g=guild.id)

    # A grantee is scoped by pam_guild_id and leaves current_guild_id unset —
    # a matching current_guild_id reads as proof of membership, which is the
    # one thing a grantee does not have.
    reader = await role_session("app_user")
    await set_rls_context(
        reader, user_id=support.id, pam_guild_id=guild.id, pam_read=True
    )
    with pytest.raises(Exception) as refused:
        await reader.exec(insert)
    message = str(refused.value).lower()
    assert "permission denied" in message or "row-level security" in message, (
        refused.value
    )
    await reader.rollback()

    # The same window at write level is what posting takes.
    writer = await role_session("app_user")
    await set_rls_context(
        writer,
        user_id=support.id,
        pam_guild_id=guild.id,
        pam_read=True,
        pam_write=True,
    )
    await writer.exec(insert)
    await writer.rollback()


# The canonical per-tool factory registry rather than a copy of it: that one
# is checked against the Tool enum at import time, so a new tool cannot reach
# these parametrized cases without a factory behind it.
_TOOL_FACTORIES = TOOL_FACTORIES


@pytest.mark.database
class TestCommentRlsLegs:
    """Comments carry one RLS leg per parent, rendered from the same
    declaration for every tool. These run under the real ``app_user`` login,
    because the subject is what the policy itself returns."""

    @pytest.mark.parametrize("tool", list(Tool))
    async def test_a_tool_comment_is_scoped_to_its_initiative(
        self, session, role_session, tool
    ):
        owner = await create_user(session)
        guild = await create_guild(session, creator=owner)
        init = await create_initiative(session, guild, owner)
        entity = await _TOOL_FACTORIES[tool](session, init, owner)
        comment = await create_comment(session, owner, **{tool.value: entity})

        outsider = await create_user(session)
        await create_guild_membership(session, user=outsider, guild=guild)

        count_sql = text(
            f"SELECT count(*) FROM comments WHERE {tool.value}_id = :eid"  # noqa: S608 — column name from the Tool enum
        ).bindparams(eid=entity.id)

        s = await role_session("app_user")
        await set_rls_context(
            s,
            user_id=outsider.id,
            guild_id=guild.id,
            guild_role=GuildRole.member.value,
        )
        assert (await s.exec(count_sql)).scalar() == 0

        member = await role_session("app_user")
        await set_rls_context(
            member,
            user_id=owner.id,
            guild_id=guild.id,
            guild_role=GuildRole.member.value,
        )
        assert (await s.exec(count_sql)).scalar() == 0  # outsider still sees none
        assert (await member.exec(count_sql)).scalar() == 1
        assert comment.id is not None
