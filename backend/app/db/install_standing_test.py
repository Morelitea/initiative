"""An installed app's standing, computed from rows and read by the gates.

``establish_install_access`` routes a session as ``guild_<id>_app`` and runs
the install standing statement. These tests set an install up the way a
community does — placed in initiatives, granted scopes by its seat, registered
by the operator — route a real request login through the seam, and check two
things: that what the statement returned is what the rows say, and that the
existing gates answer from it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from datetime import datetime, timezone

from app.api.deps import InstallAccessError, VerifiedInstall, establish_install_access
from app.core.app_scopes import ALL_SCOPES
from app.core.tools import Tool
from app.db.guild_standing import InstallContext
from app.db.request_context import ContextShapeError, InstallScoped, classify
from app.db.schema_provisioning import guild_schema_name, GuildRoleKind, guild_role_name
from app.db.session import (
    _RLS_ESTABLISHED_INFO_KEY,
    RLS_CONTEXT_MAX_AGE_SECONDS,
    StaleAuthorizationContext,
    install_context,
)
from app.models.platform.guild import GuildRole, GuildStatus
from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
from app.models.tenant.app_placement import AppPlacement
from app.models.tenant.initiative import Initiative
from app.models.tenant.document import Document
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.initiative import PermissionKey
from app.services.platform.identity_refs import ensure_ref
from app.testing import (
    create_resource_grant,
    create_app_service_registration,
    create_document,
    create_guild_app,
    create_initiative,
    route_as,
    route_as_install,
    route_session_to_guild,
)

CLIENT = "tests.install-standing"
LISTING = "INSTALLSTAND01"
_APP_DEFINITION = {
    "app_kind": "service",
    "service": {"public_id": CLIENT, "protocol": 1},
}


# ---------------------------------------------------------------------------
# Setting an install up
# ---------------------------------------------------------------------------


class _Install:
    """What a test needs to name: the community, the install, and the two
    initiatives it may be placed in."""

    def __init__(self, seat, app: GuildApp, second) -> None:
        self.seat = seat
        self.guild = seat.guild
        self.app = app
        self.a = seat.initiative
        self.b = second


async def _install(
    session,
    acting_user,
    role_session,
    *,
    granted: list[str],
    placed: str = "ab",
    requested: tuple[str, ...] = ALL_SCOPES,
) -> _Install:
    """An install placed in ``placed`` (of initiatives A and B), granted
    ``granted`` by the community's seat, with a live registration and a pinned
    manifest requesting ``requested``."""
    seat = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
    second = await create_initiative(session, seat.guild, seat.user, name="B")
    definition = {
        **_APP_DEFINITION,
        "service": {**_APP_DEFINITION["service"], "scopes": list(requested)},
    }
    app = await create_guild_app(
        session, seat.guild, seat.user, definition=definition, listing_uid=LISTING
    )
    await create_app_service_registration(
        session, public_id=CLIENT, listing_uid=LISTING
    )
    install = _Install(seat, app, second)

    await route_session_to_guild(session, seat.guild.id)
    for key, initiative in (("a", install.a), ("b", install.b)):
        if key in placed:
            session.add(AppPlacement(install_id=app.id, initiative_id=initiative.id))
    await session.commit()

    if granted:
        # Granted the way a community grants it: by its seat.
        s = await role_session("app_user")
        await route_as(s, user_id=seat.user.id, guild_id=seat.guild.id)
        row = (await s.exec(select(GuildApp).where(GuildApp.id == app.id))).one()
        row.granted_scopes = granted
        s.add(row)
        await s.commit()
    return install


async def _route(role_session, install: _Install, scopes, *, initiative_id=None):
    s = await role_session("app_user")
    context = await route_as_install(
        s,
        guild_id=install.guild.id,
        install_id=install.app.id,
        client_id=CLIENT,
        scopes=scopes,
        initiative_id=initiative_id,
    )
    return s, context


def _keys(initiative_ids, keys) -> set[str]:
    return {f"{i}:{k}" for i in initiative_ids for k in keys}


_ALL_KEYS = {key.value for key in PermissionKey}


# ---------------------------------------------------------------------------
# The standing is what the rows say
# ---------------------------------------------------------------------------


async def test_the_standing_is_what_the_rows_say(session, acting_user, role_session):
    install = await _install(
        session,
        acting_user,
        role_session,
        granted=["documents:write", "comments:read"],
    )
    s, context = await _route(
        role_session, install, ["documents:write", "comments:read"]
    )

    # What a superuser reads from the same rows.
    await route_session_to_guild(session, install.guild.id)
    placed = sorted(
        (
            await session.exec(
                select(AppPlacement.initiative_id).where(
                    AppPlacement.install_id == install.app.id
                )
            )
        ).all()
    )
    assert placed == sorted([install.a.id, install.b.id])

    granted = _keys(placed, {"documents_enabled", "create_documents"})
    assert context.live
    assert context.standing_guild_id == install.guild.id
    assert sorted(context.member_initiatives) == placed
    assert set(context.role_grants) == granted
    assert set(context.role_denies) == _keys(placed, _ALL_KEYS) - granted
    assert f"{install.a.id}:projects_enabled" in context.role_denies
    assert set(context.install_read) == {"documents", "comments"}
    assert set(context.install_write) == {"documents"}
    switched_on = {
        f"{initiative.id}:{tool.value}"
        for initiative in (
            await session.exec(select(Initiative).where(Initiative.id.in_(placed)))
        ).all()
        for tool in Tool
        if getattr(initiative, tool.view_permission)
    }
    assert set(context.enabled_tools) == switched_on

    # And what the policies will read is the same thing.
    values = (
        await s.exec(
            text(
                "SELECT current_user, "
                "current_setting('app.current_user_id', true), "
                "current_setting('app.current_install_id', true), "
                "current_setting('app.member_initiatives', true), "
                "current_setting('app.guild_admin', true), "
                "current_setting('app.guild_auth_ok', true), "
                "current_setting('app.install_write', true), "
                "(current_standing()).install_id"
            )
        )
    ).one()
    assert values[0] == guild_role_name(install.guild.id, GuildRoleKind.app)
    assert values[1] == ""
    assert values[2] == str(install.app.id)
    assert values[3] == ",".join(str(i) for i in placed)
    assert values[4] == "false"
    assert values[5] == "true"
    assert values[6] == "documents"
    assert values[7] == install.app.id
    assert install_context(s) == context
    await s.rollback()


async def test_a_narrowed_token_stands_in_one_initiative(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["documents:write"]
    )
    s, context = await _route(
        role_session, install, ["documents:write"], initiative_id=install.a.id
    )
    assert context.member_initiatives == (install.a.id,)
    assert set(context.role_grants) == _keys(
        [install.a.id], {"documents_enabled", "create_documents"}
    )
    assert {pair.split(":")[0] for pair in context.role_denies} == {str(install.a.id)}
    await s.rollback()


@pytest.mark.parametrize(
    "granted,token,read,write,requested",
    [
        # The token asks for less than the seat granted.
        (
            ["documents:write", "projects:write"],
            ["documents:read"],
            {"documents"},
            set(),
            ALL_SCOPES,
        ),
        # The seat granted less than the token asks for: what both name is
        # used, at the lower of the two levels.
        (
            ["documents:read"],
            ["documents:write", "projects:write"],
            {"documents"},
            set(),
            ALL_SCOPES,
        ),
        (
            ["documents:read", "projects:write"],
            ["documents:write", "projects:write"],
            {"documents", "projects"},
            {"projects"},
            ALL_SCOPES,
        ),
        # A token issued before the pinned version stopped requesting a scope
        # carries it, and it is used no more.
        (
            ["documents:write", "projects:write"],
            ["documents:write", "projects:write"],
            {"documents"},
            {"documents"},
            ("documents:write",),
        ),
    ],
)
async def test_what_an_install_uses_is_the_grant_and_the_token_together(
    session, acting_user, role_session, granted, token, read, write, requested
):
    install = await _install(
        session, acting_user, role_session, granted=granted, requested=requested
    )
    s, context = await _route(role_session, install, token)
    assert set(context.install_read) == read
    assert set(context.install_write) == write
    await s.rollback()


# ---------------------------------------------------------------------------
# When an install may not act
# ---------------------------------------------------------------------------


async def _disable_install(session, install: _Install) -> None:
    await route_session_to_guild(session, install.guild.id)
    await session.exec(
        text("UPDATE guild_apps SET enabled = false WHERE id = :id").bindparams(
            id=install.app.id
        )
    )
    await session.commit()


async def _set_registration(session, column: str, value) -> None:
    await session.exec(
        text(
            f"UPDATE public.app_service_registrations SET {column} = :v "
            "WHERE public_id = :pid"
        ).bindparams(v=value, pid=CLIENT)
    )
    await session.commit()


async def _set_guild_status(session, install: _Install, status: GuildStatus) -> None:
    await session.exec(
        text("UPDATE public.guilds SET status = :s WHERE id = :id").bindparams(
            s=status.value, id=install.guild.id
        )
    )
    await session.commit()


@pytest.mark.parametrize(
    "reason",
    [
        "install_disabled",
        "registration_disabled",
        "registration_keyless",
        "publisher_disabled",
        "another_client",
        "guild_suspended",
        "guild_on_hold",
    ],
)
async def test_an_install_that_may_not_act_is_refused(
    session, acting_user, role_session, reason
):
    install = await _install(
        session, acting_user, role_session, granted=["documents:read"]
    )
    client = CLIENT
    if reason == "install_disabled":
        await _disable_install(session, install)
    elif reason == "registration_disabled":
        await _set_registration(session, "enabled", False)
    elif reason == "registration_keyless":
        await _set_registration(session, "jwks", None)
    elif reason == "publisher_disabled":
        await session.exec(
            text(
                "UPDATE public.publishers SET enabled = false WHERE id = "
                "(SELECT publisher_id FROM public.app_service_registrations "
                "WHERE public_id = :c)"
            ).bindparams(c=CLIENT)
        )
        await session.commit()
    elif reason == "another_client":
        client = "tests.someone-else"
    elif reason == "guild_suspended":
        await _set_guild_status(session, install, GuildStatus.suspended)
    elif reason == "guild_on_hold":
        await _set_guild_status(session, install, GuildStatus.on_hold)

    s = await role_session("app_user")
    with pytest.raises(InstallAccessError):
        await route_as_install(
            s,
            guild_id=install.guild.id,
            install_id=install.app.id,
            client_id=client,
            scopes=["documents:read"],
        )
    # Refused with an empty standing: nothing a gate reads answers yes.
    values = (
        await s.exec(
            text(
                "SELECT current_setting('app.member_initiatives', true), "
                "current_setting('app.role_grants', true), "
                "current_setting('app.install_read', true), "
                "current_setting('app.guild_auth_ok', true)"
            )
        )
    ).one()
    assert tuple(values) == ("", "", "", "false")
    await s.rollback()


async def test_a_read_only_community_writes_nothing(session, acting_user, role_session):
    install = await _install(
        session, acting_user, role_session, granted=["documents:write"]
    )
    await _set_guild_status(session, install, GuildStatus.read_only)
    s, context = await _route(role_session, install, ["documents:write"])
    assert context.live and context.read_only
    assert set(context.install_read) == {"documents"}
    assert context.install_write == ()
    assert not any(pair.endswith(":create_documents") for pair in context.role_grants)
    await s.rollback()


async def test_a_community_that_is_gone_is_refused(session, role_session):
    """No role to assume is the same refusal as an install that may not act,
    and it leaves the session unrouted."""
    s = await role_session("app_user")
    with pytest.raises(InstallAccessError):
        await route_as_install(
            s,
            guild_id=987_654_321,
            install_id=1,
            client_id=CLIENT,
            scopes=["documents:read"],
        )
    assert (await s.exec(text("SELECT current_user"))).one()[0] != (
        guild_role_name(987_654_321, GuildRoleKind.app)
    )
    await s.rollback()


async def test_an_unknown_scope_is_refused(session, acting_user, role_session):
    install = await _install(
        session, acting_user, role_session, granted=["documents:read"]
    )
    s = await role_session("app_user")
    with pytest.raises(InstallAccessError):
        await route_as_install(
            s,
            guild_id=install.guild.id,
            install_id=install.app.id,
            client_id=CLIENT,
            scopes=["documents:read", "everything:write"],
        )


# ---------------------------------------------------------------------------
# The gates answer from it
# ---------------------------------------------------------------------------


async def test_the_gates_answer_for_an_install(session, acting_user, role_session):
    """Placement is gate 2, the role keys its scopes give are gate 3, and a
    share with every member of an initiative it is placed in is gate 4. A
    document shared with one person is not the install's."""
    install = await _install(
        session, acting_user, role_session, granted=["documents:read"]
    )
    shared_a = await create_document(
        session, install.a, install.seat.user, name="Shared A"
    )
    await create_resource_grant(session, shared_a, all_initiative_members=True)
    await create_document(session, install.a, install.seat.user, name="Private A")
    shared_b = await create_document(
        session, install.b, install.seat.user, name="Shared B"
    )
    await create_resource_grant(session, shared_b, all_initiative_members=True)

    s, _context = await _route(role_session, install, ["documents:read"])
    assert set((await s.exec(select(Document.name))).all()) == {
        "Shared A",
        "Shared B",
    }
    await s.rollback()

    narrowed, _context = await _route(
        role_session, install, ["documents:read"], initiative_id=install.a.id
    )
    assert set((await narrowed.exec(select(Document.name))).all()) == {"Shared A"}
    await narrowed.rollback()


async def test_an_install_without_a_tool_scope_reads_none_of_it(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["comments:read"]
    )
    shared = await create_document(session, install.a, install.seat.user)
    await create_resource_grant(session, shared, all_initiative_members=True)
    s, context = await _route(role_session, install, ["comments:read"])
    assert f"{install.a.id}:documents_enabled" in context.role_denies
    assert (await s.exec(select(Document.name))).all() == []
    await s.rollback()


async def test_the_app_role_cannot_read_the_communitys_settings(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["documents:read"]
    )
    s, _context = await _route(role_session, install, ["documents:read"])
    with pytest.raises(DBAPIError, match="permission denied"):
        await s.exec(
            text(
                f'SELECT count(*) FROM "{guild_schema_name(install.guild.id)}"'
                ".guild_settings"
            )
        )
    await s.rollback()


# ---------------------------------------------------------------------------
# Round trips and replay
# ---------------------------------------------------------------------------


async def test_the_seam_is_two_statements(session, acting_user, role_session):
    install = await _install(
        session, acting_user, role_session, granted=["documents:read"]
    )
    s = await role_session("app_user")
    await s.connection()
    statements: list[str] = []

    def count(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    engine = s.bind.sync_engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        await route_as_install(
            s,
            guild_id=install.guild.id,
            install_id=install.app.id,
            client_id=CLIENT,
            scopes=["documents:read"],
        )
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(statements) == 2, statements
    await s.rollback()


async def test_a_new_transaction_replays_the_install(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["documents:read"]
    )
    s, context = await _route(role_session, install, ["documents:read"])
    await s.commit()
    values = (
        await s.exec(
            text(
                "SELECT current_user, "
                "current_setting('app.member_initiatives', true), "
                "current_setting('app.install_read', true), "
                "current_setting('app.guild_auth_ok', true)"
            )
        )
    ).one()
    assert tuple(values) == (
        guild_role_name(install.guild.id, GuildRoleKind.app),
        ",".join(str(i) for i in context.member_initiatives),
        "documents",
        "true",
    )
    await s.commit()

    s.info[_RLS_ESTABLISHED_INFO_KEY] -= RLS_CONTEXT_MAX_AGE_SECONDS + 1
    with pytest.raises(StaleAuthorizationContext):
        await s.exec(text("SELECT 1"))


# ---------------------------------------------------------------------------
# What the install floor holds in public
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table,readable",
    [
        ("guilds", {"id", "status"}),
        (
            "app_service_registrations",
            {
                "public_id",
                "listing_uid",
                "enabled",
                "publisher_id",
                "jwks",
                "jwks_uri",
                "base_url",
                "vendor_ready",
            },
        ),
        # Whether the registration's publisher is on.
        ("publishers", {"id", "enabled"}),
        # A member token's standing: the member's own membership row and
        # whether their account is active.
        ("guild_memberships", {"guild_id", "user_id"}),
        ("users", {"id", "status"}),
    ],
)
async def test_the_install_floor_reads_only_what_its_standing_needs(
    session, table, readable
):
    rows = (
        await session.exec(
            text(
                "SELECT column_name, "
                "has_column_privilege('app_install_base', "
                "CAST(:t AS text), column_name, 'SELECT') "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :name"
            ).bindparams(t=f"public.{table}", name=table)
        )
    ).all()
    assert {name for name, held in rows if held} == readable


async def _sector_refs(session, install: _Install) -> dict[str, str]:
    """References in and around the install's sector, minted as the system
    engine would: the seat's and the community's in its own sector, the seat's
    at another install, and the seat's for billing."""
    guild_id, install_id, user_id = (
        install.guild.id,
        install.app.id,
        install.seat.user.id,
    )
    refs = {
        "own": await ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=user_id,
            purpose=IdentityPurpose.app,
            sector_guild_id=guild_id,
            sector_id=install_id,
        ),
        "guild": await ensure_ref(
            session,
            entity_type=IdentityEntity.guild,
            entity_id=guild_id,
            purpose=IdentityPurpose.app,
            sector_guild_id=guild_id,
            sector_id=install_id,
        ),
        "other_install": await ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=user_id,
            purpose=IdentityPurpose.app,
            sector_guild_id=guild_id,
            sector_id=install_id + 1000,
        ),
        "billing": await ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=user_id,
            purpose=IdentityPurpose.billing,
        ),
    }
    await session.commit()
    return refs


async def test_the_standing_resolves_only_the_install_s_own_references(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["documents:read"]
    )
    refs = await _sector_refs(session, install)

    s = await role_session("app_user")
    context = await establish_install_access(
        s,
        VerifiedInstall(
            guild_id=install.guild.id,
            install_id=install.app.id,
            client_id=CLIENT,
            scopes=frozenset({"documents:read"}),
        ),
        [*refs.values(), "uapp_nobody-at-all", "plain text"],
    )

    assert context.guild_ref == refs["guild"]
    assert context.named_refs == tuple(
        sorted(
            [
                (refs["own"], IdentityEntity.user.value, install.seat.user.id),
                (refs["guild"], IdentityEntity.guild.value, install.guild.id),
            ]
        )
    )
    await s.rollback()


async def test_the_install_role_reads_and_mints_in_its_own_sector_only(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["documents:read"]
    )
    refs = await _sector_refs(session, install)
    s, _context = await _route(role_session, install, ["documents:read"])

    visible = set(
        (await s.exec(text("SELECT ref FROM public.identity_refs"))).scalars().all()
    )
    assert visible == {refs["own"], refs["guild"]}

    insert = text(
        "INSERT INTO public.identity_refs "
        "(ref, entity_type, entity_id, purpose, sector_guild_id, sector_id, "
        "created_at, retired_at) "
        "VALUES (:ref, :kind, :entity, :purpose, :g, :i, now(), :retired)"
    )
    own_sector = dict(
        kind="user",
        entity=install.seat.user.id + 1,
        purpose="app",
        g=install.guild.id,
        i=install.app.id,
        retired=None,
    )

    async def attempt(sql, **values) -> bool:
        try:
            async with s.begin_nested():
                await s.exec(sql.bindparams(**values))
        except DBAPIError:
            return False
        return True

    assert await attempt(insert, ref="uapp_minted-here", **own_sector)
    for n, refused in enumerate(
        (
            {"i": install.app.id + 1000},
            {"g": install.guild.id + 1000},
            {"purpose": "billing"},
            {"kind": "guild", "entity": install.guild.id + 1000},
            {"retired": datetime.now(timezone.utc)},
        )
    ):
        assert not await attempt(
            insert, ref=f"uapp_refused-{n}", **{**own_sector, **refused}
        ), refused
    assert not await attempt(
        text("UPDATE public.identity_refs SET retired_at = now() WHERE ref = :r"),
        r=refs["own"],
    )
    assert not await attempt(
        text("DELETE FROM public.identity_refs WHERE ref = :r"), r=refs["own"]
    )
    await s.rollback()


# ---------------------------------------------------------------------------
# The routing shape
# ---------------------------------------------------------------------------


def _pending(**overrides) -> InstallContext:
    fields = dict(guild_id=3, install_id=5, client_id=CLIENT, token_scopes=frozenset())
    fields.update(overrides)
    return InstallContext(**fields)


def test_an_install_routing_is_its_own_shape():
    shape = classify(
        guild_id=3,
        install_id=5,
        context=_pending(),
        token_client_id=CLIENT,
        token_scopes=frozenset({"documents:read"}),
    )
    assert isinstance(shape, InstallScoped)


@pytest.mark.parametrize(
    "kwargs",
    [
        # A person and an install together.
        dict(guild_id=3, install_id=5, user_id=7, token_client_id=CLIENT),
        # No context.
        dict(guild_id=3, install_id=5, context=None, token_client_id=CLIENT),
        # No community.
        dict(guild_id=None, install_id=5, token_client_id=CLIENT),
        # A context for another install.
        dict(
            guild_id=3,
            install_id=6,
            token_client_id=CLIENT,
        ),
        # A grant beside it.
        dict(guild_id=3, install_id=5, token_client_id=CLIENT, pam_read=True),
    ],
)
def test_an_install_routing_refuses_what_is_not_its_own(kwargs):
    kwargs.setdefault("context", _pending())
    with pytest.raises(ContextShapeError):
        classify(**kwargs)


def test_an_install_context_never_routes_as_a_sweep():
    """A community routing with nobody behind it is a system sweep; carrying an
    install's context without its install id is refused rather than read as
    one."""
    with pytest.raises(ContextShapeError):
        classify(guild_id=3, context=_pending())
    with pytest.raises(ContextShapeError):
        classify(guild_id=3, token_client_id=CLIENT)
