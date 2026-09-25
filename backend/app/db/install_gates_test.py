"""An installed app answers to its scopes at every gate.

``install_standing_test`` shows the standing is what the rows say. These show
the gates read it: an install routed through the seam on the real request
login reaches content only under the scope that names it, a token narrowed to
one initiative reaches nothing that belongs to the community as a whole, a
grant naming the install is how sharing reaches it, and the tables no tool
governs ask their own scope. Each surface also runs one ordinary member's
read or write through the same policies, so the legs are seen to leave a
person's request as it was.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.core.tools import Tool
from app.db.app_rls import APP_REFUSED_TABLES, APP_TABLE_ACCESS
from app.db.guild_ddl import APP_POLICY_TABLES, render_guild_rls_ddl
from app.db.install_standing_test import (
    _install,
    _route,
)
from app.models.platform.guild import GuildRole
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.comment import Comment
from app.models.tenant.document import Document, DocumentType
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.models.tenant.tag import Tag
from app.testing import (
    create_resource_grant,
    create_calendar,
    create_calendar_event,
    create_comment,
    create_document,
    create_tag,
    route_as,
    route_session_to_guild,
)

_INSTALL_LEG = "app.current_install_id"


# ---------------------------------------------------------------------------
# The render: every table an app reaches asks its scope
# ---------------------------------------------------------------------------

_POLICY = re.compile(
    r"^CREATE POLICY (\w+) ON (\w+) AS (PERMISSIVE|RESTRICTIVE) FOR (\w+)\n  (.*?);$",
    re.M | re.S,
)


def _policies() -> dict[str, list[tuple[str, str, str]]]:
    """table -> (kind, command, predicate) for every rendered policy."""
    out: dict[str, list[tuple[str, str, str]]] = {}
    for _name, table, kind, command, body in _POLICY.findall(render_guild_rls_ddl()):
        out.setdefault(table, []).append((kind, command, body))
    return out


def _asks_the_install(policies, table: str, command: str) -> bool:
    return any(
        _INSTALL_LEG in body
        for _kind, cmd, body in policies.get(table, [])
        if cmd in (command, "ALL")
    )


def _read_asks_the_install(policies, table: str, seen: frozenset[str] = frozenset()):
    """A table's read asks the install itself, or walks into a table whose
    read does: a child's read is an EXISTS into its parent, and the parent's
    own read policy is what runs there."""
    if _asks_the_install(policies, table, "SELECT"):
        return True
    read = " ".join(
        body for _kind, cmd, body in policies.get(table, []) if cmd == "SELECT"
    )
    walked = set(re.findall(r"\b(?:FROM|JOIN) (\w+)\b", read)) - seen - {table}
    return any(
        _read_asks_the_install(policies, parent, seen | {table})
        for parent in walked
        if parent in policies
    )


@pytest.mark.unit
@pytest.mark.parametrize("command", ["SELECT", "INSERT", "UPDATE", "DELETE"])
def test_every_table_an_app_reaches_asks_the_install(command):
    """Each command on each table the app role is granted carries the leg in
    its own policies. A child's read is the one exception: it is an EXISTS
    into its parent, and that parent's own read asks."""
    policies = _policies()
    missing = [
        table
        for table in sorted(APP_TABLE_ACCESS)
        if not (
            _read_asks_the_install(policies, table)
            if command == "SELECT"
            else _asks_the_install(policies, table, command)
        )
    ]
    assert missing == [], f"{command} asks nothing of an install on {missing}"


@pytest.mark.unit
def test_the_refused_tables_refuse_every_command():
    policies = _policies()
    for table in sorted(APP_REFUSED_TABLES):
        assert table not in APP_TABLE_ACCESS, table
        for command in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert _asks_the_install(policies, table, command), (table, command)


@pytest.mark.unit
def test_the_app_policies_are_restrictive():
    """They narrow what the table's own policies admit, and admit nothing."""
    found: dict[str, set[str]] = {}
    for name, table, kind, _command, _body in _POLICY.findall(render_guild_rls_ddl()):
        if name.startswith("app_scope_"):
            assert kind == "RESTRICTIVE", (table, name)
            found.setdefault(table, set()).add(name)
    assert set(found) == set(APP_POLICY_TABLES)


# ---------------------------------------------------------------------------
# A person, for the same surfaces
# ---------------------------------------------------------------------------


async def _member(acting_user, install):
    """An ordinary member of initiative A."""
    return await acting_user(
        guild_role=GuildRole.member,
        guild=install.guild,
        initiative=install.a,
        initiative_role="member",
    )


async def _as_person(role_session, actor, install):
    s = await role_session("app_user")
    await route_as(s, user_id=actor.user.id, guild_id=install.guild.id)
    return s


async def _rename(s, document_id: int, name: str) -> int:
    result = await s.exec(
        text("UPDATE documents SET name = :n WHERE id = :id").bindparams(
            n=name, id=document_id
        )
    )
    return result.rowcount


# ---------------------------------------------------------------------------
# Tool content
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_document_is_read_with_read_and_changed_with_write(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["documents:write"]
    )
    document = await create_document(
        session, install.a, install.seat.user, name="Shared"
    )
    await create_resource_grant(session, document, all_initiative_members=True)
    # A write grant naming the install; the scope still decides.
    await create_resource_grant(
        session,
        document,
        app_install_id=install.app.id,
        level=ResourceAccessLevel.write,
    )

    reader, _ = await _route(role_session, install, ["documents:read"])
    assert (await reader.exec(select(Document.name))).all() == ["Shared"]
    assert await _rename(reader, document.id, "Changed by a reader") == 0
    await reader.rollback()

    writer, _ = await _route(role_session, install, ["documents:write"])
    assert await _rename(writer, document.id, "Changed by a writer") == 1
    await writer.rollback()

    # A member's own write grant still answers for them.
    member = await _member(acting_user, install)
    await create_resource_grant(
        session, document, user=member.user, level=ResourceAccessLevel.write
    )
    person = await _as_person(role_session, member, install)
    assert (await person.exec(select(Document.name))).all() == ["Shared"]
    assert await _rename(person, document.id, "Changed by a member") == 1
    await person.rollback()


@pytest.mark.integration
async def test_a_private_document_is_the_installs_once_a_grant_names_it(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["documents:read"]
    )
    private = await create_document(
        session, install.a, install.seat.user, name="Private"
    )

    s, _ = await _route(role_session, install, ["documents:read"])
    assert (await s.exec(select(Document.name))).all() == []
    await s.rollback()

    await create_resource_grant(
        session, private, app_install_id=install.app.id, level=ResourceAccessLevel.read
    )
    s, _ = await _route(role_session, install, ["documents:read"])
    assert (await s.exec(select(Document.name))).all() == ["Private"]
    await s.rollback()


@pytest.mark.integration
async def test_creating_asks_the_scope_of_what_is_created(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["documents:write"]
    )

    s, _ = await _route(role_session, install, ["documents:write"])
    s.add(Project(initiative_id=install.a.id, name="Not the app's to make"))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()
    await s.rollback()

    s, _ = await _route(role_session, install, ["documents:write"])
    made = Document(
        initiative_id=install.a.id,
        name="Made by the app",
        document_type=DocumentType.native,
    )
    s.add(made)
    await s.flush()
    # The database wrote the owner row, naming the install and nobody else.
    grants = (
        await s.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == Tool.document.value,
                ResourceGrant.resource_id == made.id,
            )
        )
    ).all()
    assert [
        (g.level, g.app_install_id, g.user_id, g.initiative_id) for g in grants
    ] == [(ResourceAccessLevel.owner, install.app.id, None, install.a.id)]
    assert (
        await s.exec(select(Document.name).where(Document.id == made.id))
    ).all() == ["Made by the app"]
    await s.rollback()


@pytest.mark.integration
async def test_a_person_creating_a_document_gets_no_install_grant(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["documents:write"]
    )
    person = await _as_person(role_session, install.seat, install)
    made = Document(
        initiative_id=install.a.id,
        name="Made by a person",
        document_type=DocumentType.native,
    )
    person.add(made)
    await person.flush()
    rows = (
        await person.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == Tool.document.value,
                ResourceGrant.resource_id == made.id,
            )
        )
    ).all()
    assert rows == []
    await person.rollback()


@pytest.mark.integration
@pytest.mark.parametrize("target", ["owned", "unowned", "its_own", "for_a_person"])
async def test_an_install_writes_no_grant_itself(
    session, acting_user, role_session, target
):
    """Every grant row an install's request inserts directly is refused: an
    owner row naming itself on a document it can read, owned or not, and any
    row on a document it has just made."""
    install = await _install(
        session, acting_user, role_session, granted=["documents:write"]
    )
    owned = await create_document(session, install.a, install.seat.user)
    await create_resource_grant(session, owned, all_initiative_members=True)
    unowned = await create_document(session, install.a, install.seat.user)
    await create_resource_grant(session, unowned, all_initiative_members=True)
    await route_session_to_guild(session, install.guild.id)
    await session.exec(
        text(
            "DELETE FROM resource_grants WHERE resource_type = 'document' "
            "AND resource_id = :id AND level = 'owner'"
        ).bindparams(id=unowned.id)
    )
    await session.commit()

    s, _ = await _route(role_session, install, ["documents:write"])
    if target in ("owned", "unowned"):
        resource_id = (owned if target == "owned" else unowned).id
        row = ResourceGrant(
            resource_type=Tool.document.value,
            resource_id=resource_id,
            app_install_id=install.app.id,
            level=ResourceAccessLevel.owner,
            initiative_id=install.a.id,
        )
    else:
        made = Document(
            initiative_id=install.a.id,
            name="Made by the app",
            document_type=DocumentType.native,
        )
        s.add(made)
        await s.flush()
        row = ResourceGrant(
            resource_type=Tool.document.value,
            resource_id=made.id,
            level=ResourceAccessLevel.read,
            initiative_id=install.a.id,
            **(
                {"all_initiative_members": True}
                if target == "its_own"
                else {"user_id": install.seat.user.id}
            ),
        )
    s.add(row)
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()
    await s.rollback()


@pytest.mark.integration
async def test_a_narrowed_token_reaches_nothing_of_the_community_as_a_whole(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["calendars:read"]
    )
    calendar = await create_calendar(
        session, install.a, install.seat.user, name="Community", initiative_id=None
    )
    await create_calendar_event(session, calendar, install.seat.user, title="Picnic")

    calendars = select(Calendar.name).where(Calendar.id == calendar.id)
    events = select(CalendarEvent.title).where(CalendarEvent.calendar_id == calendar.id)

    whole, _ = await _route(role_session, install, ["calendars:read"])
    assert (await whole.exec(calendars)).all() == ["Community"]
    assert (await whole.exec(events)).all() == ["Picnic"]
    await whole.rollback()

    narrowed, _ = await _route(
        role_session, install, ["calendars:read"], initiative_id=install.a.id
    )
    assert (await narrowed.exec(calendars)).all() == []
    assert (await narrowed.exec(events)).all() == []
    await narrowed.rollback()


# ---------------------------------------------------------------------------
# The surfaces that span tools
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_comments_ask_the_comments_scope(session, acting_user, role_session):
    install = await _install(
        session,
        acting_user,
        role_session,
        granted=["documents:read", "comments:write"],
    )
    document = await create_document(session, install.a, install.seat.user)
    await create_resource_grant(session, document, all_initiative_members=True)
    await create_comment(session, install.seat.user, document=document, content="First")

    s, _ = await _route(role_session, install, ["documents:read"])
    assert (await s.exec(select(Comment.content))).all() == []
    await s.rollback()

    s, _ = await _route(role_session, install, ["documents:read", "comments:read"])
    assert (await s.exec(select(Comment.content))).all() == ["First"]
    s.add(Comment(content="From a reader", document_id=document.id))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()
    await s.rollback()

    s, _ = await _route(role_session, install, ["documents:read", "comments:write"])
    s.add(Comment(content="From the app", document_id=document.id))
    await s.flush()
    assert set((await s.exec(select(Comment.content))).all()) == {
        "First",
        "From the app",
    }
    await s.rollback()

    member = await _member(acting_user, install)
    person = await _as_person(role_session, member, install)
    assert (await person.exec(select(Comment.content))).all() == ["First"]
    person.add(Comment(content="From a member", document_id=document.id))
    await person.flush()
    await person.rollback()


@pytest.mark.integration
async def test_tags_ask_the_tags_scope(session, acting_user, role_session):
    install = await _install(
        session,
        acting_user,
        role_session,
        granted=["tags:write", "documents:read"],
    )
    await create_tag(session, install.guild, name="urgent")

    s, _ = await _route(role_session, install, ["documents:read"])
    assert (await s.exec(select(Tag.name))).all() == []
    await s.rollback()

    s, _ = await _route(role_session, install, ["tags:read"])
    assert "urgent" in (await s.exec(select(Tag.name))).all()
    s.add(Tag(name="from-a-reader"))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()
    await s.rollback()

    s, _ = await _route(role_session, install, ["tags:write"])
    s.add(Tag(name="from-the-app"))
    await s.flush()
    await s.rollback()

    member = await _member(acting_user, install)
    person = await _as_person(role_session, member, install)
    assert "urgent" in (await person.exec(select(Tag.name))).all()
    await person.rollback()


# ---------------------------------------------------------------------------
# Structure and subscriptions
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_roster_is_read_with_members_read_and_never_written(
    session, acting_user, role_session
):
    install = await _install(
        session,
        acting_user,
        role_session,
        granted=["members:read", "documents:read"],
    )

    s, _ = await _route(role_session, install, ["documents:read"])
    assert (await s.exec(select(InitiativeMember.user_id))).all() == []
    await s.rollback()

    s, _ = await _route(role_session, install, ["members:read"])
    assert (
        install.seat.user.id in (await s.exec(select(InitiativeMember.user_id))).all()
    )
    with pytest.raises(DBAPIError):
        await s.exec(
            text("DELETE FROM initiative_members WHERE user_id = :u").bindparams(
                u=install.seat.user.id
            )
        )
    await s.rollback()


async def _subscription(session, install, *, app_install_id, url: str) -> None:
    await route_session_to_guild(session, install.guild.id)
    await session.exec(
        text(
            "INSERT INTO webhook_subscriptions (initiative_id, app_install_id,"
            " target_url, hmac_secret, event_types, created_at, updated_at)"
            " VALUES (:i, :a, :u, 's3cret', ARRAY['documents.created'],"
            " now(), now())"
        ).bindparams(i=install.a.id, a=app_install_id, u=url)
    )
    await session.commit()


@pytest.mark.integration
async def test_an_install_sees_only_its_own_subscriptions(
    session, acting_user, role_session
):
    install = await _install(
        session, acting_user, role_session, granted=["documents:read"]
    )
    await _subscription(
        session, install, app_install_id=install.app.id, url="https://app.test/own"
    )
    await _subscription(
        session, install, app_install_id=None, url="https://member.test/theirs"
    )

    s, _ = await _route(role_session, install, ["documents:read"])
    urls = (await s.exec(text("SELECT target_url FROM webhook_subscriptions"))).all()
    assert [row[0] for row in urls] == ["https://app.test/own"]
    changed = await s.exec(
        text(
            "UPDATE webhook_subscriptions SET active = false WHERE app_install_id IS NULL"
        )
    )
    assert changed.rowcount == 0
    await s.rollback()


@pytest.mark.integration
async def test_every_tool_table_writes_an_installs_owner_row(session, acting_user):
    """The trigger list is stated in its migration; the catalog is what a new
    tool has to match."""
    a = await acting_user(guild_role=GuildRole.admin)
    rows = await session.exec(
        text(
            "SELECT c.relname FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema AND NOT t.tgisinternal "
            "AND t.tgfoid = 'public.fn_install_owns_what_it_creates()'::regprocedure"
        ).bindparams(schema=f"guild_{a.guild.id}")
    )
    assert set(rows.all()) >= {(tool.plural,) for tool in Tool}
