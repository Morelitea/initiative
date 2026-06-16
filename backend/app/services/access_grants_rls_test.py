"""DB-level RLS isolation tests for PAM grants.

The test database connects as a BYPASSRLS superuser, so these tests explicitly
``SET ROLE app_user`` (the non-privileged role the app uses at runtime) to make
RLS + FORCE ROW LEVEL SECURITY actually apply. Without that, the policies would
silently pass and prove nothing.
"""

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.pam_context import set_active_grant
from app.db.session import set_rls_context
from app.models.counter import CounterGroup
from app.models.document import Document
from app.models.user import UserRole
from app.services import app_settings as app_settings_service
from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_queue,
    create_user,
)


async def _set_app_user(session: AsyncSession) -> None:
    await session.execute(text("SET ROLE app_user"))


async def _reset_role(session: AsyncSession) -> None:
    await session.execute(text("RESET ROLE"))


@pytest.mark.integration
async def test_pam_read_grant_sees_only_granted_guild(session: AsyncSession):
    owner = await create_user(session, email="owner@example.com", role=UserRole.owner)
    support = await create_user(
        session, email="support@example.com", role=UserRole.support
    )

    guild_a = await create_guild(session, creator=owner)
    init_a = await create_initiative(session, guild_a, owner)
    proj_a = await create_project(session, init_a, owner, name="Alpha")
    doc_a = Document(
        guild_id=guild_a.id,
        initiative_id=init_a.id,
        title="Alpha Doc",
        content={},
        created_by_id=owner.id,
        updated_by_id=owner.id,
    )
    session.add(doc_a)
    await session.commit()
    await session.refresh(doc_a)

    guild_b = await create_guild(session, creator=owner)
    init_b = await create_initiative(session, guild_b, owner)
    await create_project(session, init_b, owner, name="Bravo")

    try:
        await _set_app_user(session)

        # Live READ grant scoped to guild A.
        await set_rls_context(
            session,
            user_id=support.id,
            pam_guild_id=guild_a.id,
            pam_read=True,
            pam_write=False,
        )

        # The guild row itself must be readable — get_guild_membership fetches
        # it to build the request context, so without this every guild-scoped
        # endpoint 500s for a grantee.
        visible_guild = (
            await session.execute(
                text("SELECT id FROM guilds WHERE id = :g"), {"g": guild_a.id}
            )
        ).all()
        assert len(visible_guild) == 1, (
            "grantee must be able to read the granted guild row"
        )

        # Initiatives of the granted guild are visible (the sidebar list) — this
        # is the exact RLS path the empty-guild bug would break.
        visible_inits = (
            await session.execute(
                text("SELECT id FROM initiatives WHERE id = :i"), {"i": init_a.id}
            )
        ).all()
        assert len(visible_inits) == 1, (
            "read grant should see the granted guild's initiatives"
        )

        visible_a = (
            await session.execute(
                text("SELECT id FROM projects WHERE id = :p"), {"p": proj_a.id}
            )
        ).all()
        assert len(visible_a) == 1, "read grant should see the granted guild's project"

        # Documents must be visible too — the collaboration WebSocket loads the
        # document under this exact pam_read context before authorizing.
        visible_doc = (
            await session.execute(
                text("SELECT id FROM documents WHERE id = :d"), {"d": doc_a.id}
            )
        ).all()
        assert len(visible_doc) == 1, (
            "read grant should see the granted guild's documents"
        )

        # Cross-guild isolation: guild B's project lives in another schema, so it
        # is invisible here. (Query by name — its per-schema id collides with A's.)
        visible_b = (
            await session.execute(text("SELECT id FROM projects WHERE name = 'Bravo'"))
        ).all()
        assert len(visible_b) == 0, "read grant must NOT see other guilds"

        # Read grant is read-only: the read-only role has no write on the schema,
        # so a write is denied at the role level (raises permission denied).
        with pytest.raises(Exception):
            await session.execute(
                text("UPDATE projects SET name = 'hacked' WHERE name = 'Alpha'")
            )
        await session.rollback()
    finally:
        await _reset_role(session)


@pytest.mark.integration
async def test_grantee_guild_settings_lazy_create_does_not_fault(session: AsyncSession):
    """``get_or_create_guild_settings`` must not try to INSERT for a grantee.

    guild_settings is a config table off-limits to grants, so the lazy create
    would violate RLS and 500 the read-only ``/settings/ai/resolved`` (and any
    other settings read). A grantee gets a transient default instead.
    """
    owner = await create_user(
        session, email="owner-gs@example.com", role=UserRole.owner
    )
    support = await create_user(
        session, email="support-gs@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)  # no guild_settings row seeded

    try:
        await _set_app_user(session)
        await set_rls_context(
            session,
            user_id=support.id,
            pam_guild_id=guild.id,
            pam_read=True,
            pam_write=False,
        )
        set_active_grant(guild.id, "read")

        # Pre-fix this raised InsufficientPrivilegeError on the INSERT.
        row = await app_settings_service.get_or_create_guild_settings(session, guild.id)
        assert row.guild_id == guild.id
        assert row.id is None, "grantee settings must be transient, not persisted"
    finally:
        set_active_grant(None, None)
        await _reset_role(session)

    # Nothing was written.
    persisted = (
        await session.execute(
            text("SELECT count(*) FROM guild_settings WHERE guild_id = :g"),
            {"g": guild.id},
        )
    ).scalar_one()
    assert persisted == 0, "grantee read must not create a guild_settings row"


@pytest.mark.integration
async def test_pam_read_grant_does_not_fault_legacy_isolation_tables(
    session: AsyncSession,
):
    """Tables with the legacy guild_isolation policy must not 500 for a grantee.

    A grantee leaves ``current_guild_id`` unset, so a policy that casts it to
    int without a NULLIF guard raises ``invalid input syntax for type integer``
    and faults the whole query (queues, counters, …). This guards migration
    ``20260530_0095``.
    """
    owner = await create_user(session, email="owner4@example.com", role=UserRole.owner)
    support = await create_user(
        session, email="support4@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner)
    queue = await create_queue(session, init, owner, name="Ops Queue")
    cg = CounterGroup(
        guild_id=guild.id,
        initiative_id=init.id,
        name="Stats",
        created_by_id=owner.id,
    )
    session.add(cg)
    await session.commit()
    await session.refresh(cg)

    try:
        await _set_app_user(session)
        await set_rls_context(
            session,
            user_id=support.id,
            pam_guild_id=guild.id,
            pam_read=True,
            pam_write=False,
        )
        # Each of these would raise InvalidTextRepresentationError pre-0095.
        visible_q = (
            await session.execute(
                text("SELECT id FROM queues WHERE id = :q"), {"q": queue.id}
            )
        ).all()
        assert len(visible_q) == 1, "read grant should see the granted guild's queues"
        visible_cg = (
            await session.execute(
                text("SELECT id FROM counter_groups WHERE id = :c"), {"c": cg.id}
            )
        ).all()
        assert len(visible_cg) == 1, (
            "read grant should see the granted guild's counter groups"
        )
    finally:
        await _reset_role(session)


@pytest.mark.integration
async def test_no_pam_flag_sees_nothing(session: AsyncSession):
    owner = await create_user(session, email="owner2@example.com", role=UserRole.owner)
    support = await create_user(
        session, email="support2@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner)
    proj = await create_project(session, init, owner, name="Gamma")

    try:
        await _set_app_user(session)
        # Same guild context but NO pam flag — a non-member must see nothing.
        await set_rls_context(
            session,
            user_id=support.id,
            pam_guild_id=guild.id,
            pam_read=False,
            pam_write=False,
        )
        rows = (
            await session.execute(
                text("SELECT id FROM projects WHERE id = :p"), {"p": proj.id}
            )
        ).all()
        assert len(rows) == 0
    finally:
        await _reset_role(session)


@pytest.mark.integration
async def test_pam_write_grant_can_update(session: AsyncSession):
    owner = await create_user(session, email="owner3@example.com", role=UserRole.owner)
    support = await create_user(
        session, email="support3@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner)
    proj = await create_project(session, init, owner, name="Delta")

    try:
        await _set_app_user(session)
        # READ_WRITE grant sets both flags.
        await set_rls_context(
            session,
            user_id=support.id,
            pam_guild_id=guild.id,
            pam_read=True,
            pam_write=True,
        )
        result = await session.execute(
            text("UPDATE projects SET name = 'edited' WHERE id = :p"), {"p": proj.id}
        )
        assert result.rowcount == 1, "read_write grant should be able to update content"
    finally:
        await _reset_role(session)
