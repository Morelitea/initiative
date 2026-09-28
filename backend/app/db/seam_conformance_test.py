"""The seam, held to the database: every routing shape, and what it reaches.

Every route into the database is one of the shapes in
``app.db.request_context``. This suite routes each of them against one
community and reads the answers back from Postgres — never from the Python
that produced them:

* the login it runs on and the role it assumes;
* every request variable, holding exactly what the shape says and nothing it
  does not;
* one community: the schema it resolves in, the variable that names it, and
  the standing computed for it;
* what it reaches: the projects it reads and the ones it may change, against
  the row :data:`SCENARIOS` declares for it;
* the same context on the next transaction, after a commit.

A shape added to ``RequestContext`` fails
:func:`test_every_shape_has_a_scenario` until it has a scenario here, which is
where a new kind of access states what it reaches. The catalog check holds
every policy and function to the variables the registry declares.

Slow, so deselected by default: ``pytest -m seam``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable, get_args

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import gucs
from app.db.bootstrap import login_roles
from app.db.request_context import (
    Billing,
    ContentGrantee,
    Install,
    Member,
    Platform,
    RequestContext,
    SettingsGrantee,
    SystemGuild,
    SystemMaintenance,
    Unattributed,
)
from app.db.schema_provisioning import guild_schema_name
from app.db.session import routed_context, set_rls_context
from app.models.platform.guild import GuildRole
from app.models.platform.user import UserRole
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.testing import (
    create_access_grant,
    create_project,
    create_resource_grant,
    create_user,
    route_as,
    route_as_install,
)
from app.testing.app_clients import CLIENT, install_app

pytestmark = pytest.mark.seam


@dataclass
class World:
    """One community: its seat, a member of the initiative the install is
    placed in, three people holding grants, and three projects."""

    guild_id: int
    install_id: int
    owner_id: int
    member_id: int
    reader_id: int
    writer_id: int
    settings_id: int

    @property
    def schema(self) -> str:
        return guild_schema_name(self.guild_id)


async def _world(session, acting_user, role_session) -> World:
    installed = await install_app(
        session, acting_user, role_session, granted=["projects:read"]
    )
    guild, owner = installed.guild, installed.seat.user
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=guild,
        initiative=installed.placed,
        initiative_role="member",
    )
    shared = await create_project(session, installed.placed, owner, name="shared")
    await create_project(session, installed.placed, owner, name="private")
    elsewhere = await create_project(
        session, installed.unplaced, owner, name="elsewhere"
    )
    for project in (shared, elsewhere):
        await create_resource_grant(
            session,
            project,
            level=ResourceAccessLevel.read,
            all_initiative_members=True,
        )
    people = {}
    for name, purpose, level in (
        ("reader", "content", "read"),
        ("writer", "content", "read_write"),
        ("settings", "settings", "admin"),
    ):
        person = await create_user(session, role=UserRole.support)
        await create_access_grant(
            session, user=person, guild=guild, purpose=purpose, access_level=level
        )
        people[name] = person.id
    return World(
        guild_id=guild.id,
        install_id=installed.app.id,
        owner_id=owner.id,
        member_id=member.user.id,
        reader_id=people["reader"],
        writer_id=people["writer"],
        settings_id=people["settings"],
    )


Route = Callable[[World, object], Awaitable[object]]

_EVERY = frozenset({"shared", "private", "elsewhere"})
_NONE: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Scenario:
    """One way into the community, and the reach it declares."""

    name: str
    shape: type
    #: ``"app_user"`` for the request path, ``"app_admin"`` for the system
    #: engine; resolved to the deployment's login names.
    login: str
    route: Route
    reads: frozenset[str]
    writes: frozenset[str]


def _as(user: str, **kwargs) -> Route:
    return lambda w, s: route_as(
        s, user_id=getattr(w, f"{user}_id"), guild_id=w.guild_id, **kwargs
    )


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("member", Member, "app_user", _as("member"), frozenset({"shared"}), _NONE),
    Scenario("administrator", Member, "app_user", _as("owner"), _EVERY, _EVERY),
    Scenario("read grant", ContentGrantee, "app_user", _as("reader"), _EVERY, _NONE),
    Scenario(
        "read_write grant", ContentGrantee, "app_user", _as("writer"), _EVERY, _EVERY
    ),
    Scenario(
        "settings grant",
        SettingsGrantee,
        "app_user",
        _as("settings", settings=True),
        _NONE,
        _NONE,
    ),
    Scenario(
        "installed app",
        Install,
        "app_user",
        lambda w, s: route_as_install(
            s,
            guild_id=w.guild_id,
            install_id=w.install_id,
            client_id=CLIENT,
            scopes=["projects:read"],
        ),
        frozenset({"shared"}),
        _NONE,
    ),
    Scenario(
        "sweep",
        SystemGuild,
        "app_admin",
        lambda w, s: set_rls_context(s, SystemGuild(w.guild_id)),
        _EVERY,
        _EVERY,
    ),
    Scenario(
        "maintenance",
        SystemMaintenance,
        "app_admin",
        lambda w, s: set_rls_context(s, SystemMaintenance(w.guild_id)),
        _EVERY,
        _NONE,
    ),
    Scenario(
        "platform",
        Platform,
        "app_user",
        lambda w, s: set_rls_context(s, Platform(user_id=w.member_id, tier="member")),
        _NONE,
        _NONE,
    ),
    Scenario(
        "unattributed",
        Unattributed,
        "app_user",
        lambda w, s: set_rls_context(s, Unattributed()),
        _NONE,
        _NONE,
    ),
    Scenario(
        "billing",
        Billing,
        "app_user",
        lambda w, s: set_rls_context(s, Billing(w.guild_id)),
        _NONE,
        _NONE,
    ),
)


def test_every_shape_has_a_scenario():
    """A new kind of access states what it reaches before it can be merged."""
    assert set(get_args(RequestContext)) == {s.shape for s in SCENARIOS}


async def _scalar(s, sql: str):
    return (await s.exec(text(sql))).scalar_one()


async def _variables(s) -> dict[str, str]:
    """Every request variable as the database holds it, and the role and path."""
    row = (
        await s.exec(
            text(
                "SELECT "
                + ", ".join(
                    f"COALESCE({g.raw}, '') AS \"{g.bind}\"" for g in gucs.REQUEST_GUCS
                )
                + ", current_user AS \"role\", current_setting('search_path') AS sp"
            )
        )
    ).one()
    return dict(row._mapping)


async def _projects(s, sql: str) -> frozenset[str]:
    """The project names ``sql`` returns, or none where it is refused."""
    nested = await s.begin_nested()
    try:
        return frozenset(r[0] for r in (await s.exec(text(sql))).all())
    except DBAPIError:
        return _NONE
    finally:
        await nested.rollback()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
async def test_the_route_holds(session, acting_user, role_session, scenario):
    world = await _world(session, acting_user, role_session)
    logins = {"app_user": login_roles()[1].name, "app_admin": login_roles()[2].name}
    s = await role_session(scenario.login)
    await scenario.route(world, s)
    shape = routed_context(s)
    route = shape.route()

    # The shape it declared, on the login it declared.
    assert type(shape) is scenario.shape
    held = await _variables(s)
    assert await _scalar(s, "SELECT session_user") == logins[scenario.login]
    assert held["role"] == (
        logins[scenario.login] if route.role == "none" else route.role
    )

    # Every variable holds what the shape says, and nothing it does not.
    written = {g.bind: g.encode(route.values.get(g)) for g in gucs.REQUEST_GUCS}
    assert {k: held[k] for k in written} == written

    # One community, named the same way everywhere.
    if shape.guild_id is not None:
        assert held["sp"].split(",")[0].strip() == guild_schema_name(shape.guild_id)
        assert await _scalar(s, f"SELECT {gucs.ROUTED_GUILD_ID}") == shape.guild_id
        standing = getattr(shape, "standing", None)
        if standing is not None and standing.standing_guild_id is not None:
            assert held["standing_guild_id"] == str(shape.guild_id)

    # What it reaches: the row this scenario declares.
    projects = f'"{world.schema}".projects'
    assert await _projects(s, f"SELECT name FROM {projects}") == scenario.reads
    assert (
        await _projects(s, f"UPDATE {projects} SET name = name RETURNING name")
        == scenario.writes
    )

    # And the same context on the next transaction.
    await s.commit()
    assert await _variables(s) == held


#: A request variable read by name, in whatever spelling the catalog holds.
_READ = re.compile(r"current_setting\('(app\.[a-z_]+)'")


async def test_the_catalog_reads_only_declared_variables(session, acting_user):
    """Every policy and function, in ``public``, the template and a provisioned
    community, reads only the variables the registry declares."""
    guild = (await acting_user(guild_role=GuildRole.member)).guild
    schemas = ["public", "guild_template", guild_schema_name(guild.id)]
    sources = (
        await session.exec(
            text(
                "SELECT coalesce(qual, '') || ' ' || coalesce(with_check, '') "
                "FROM pg_policies WHERE schemaname = ANY(:s) "
                "UNION ALL SELECT p.prosrc FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = ANY(:s)"
            ),
            params={"s": schemas},
        )
    ).all()
    read = {name for (source,) in sources for name in _READ.findall(source)}
    declared = {g.name for g in (*gucs.REQUEST_GUCS, *gucs.FLAGS)}
    assert read, "found no reads — the catalog query is looking in the wrong place"
    assert read <= declared, sorted(read - declared)
