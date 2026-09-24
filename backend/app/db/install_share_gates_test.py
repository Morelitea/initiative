"""An installed app shares what it may share, at the database.

The app role's policies on ``resource_grants`` admit a share row only with
``sharing:write`` and the tool's write scope in the standing, on a resource
where the install holds write, and only as a read or write share with a
person, a role or all initiative members. Each case is run on the real
request login, routed as the install.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.core.tools import Tool
from app.db.install_standing_test import _install, _route, _share_with_members
from app.models.tenant.document import Document, DocumentType
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing import create_document, route_as, route_session_to_guild

pytestmark = pytest.mark.integration

_SHARES = ["documents:write", "sharing:write"]


async def _made_by_the_install(s, install) -> Document:
    made = Document(
        initiative_id=install.a.id,
        name="Made by the app",
        document_type=DocumentType.native,
    )
    s.add(made)
    await s.flush()
    return made


def _share(document_id: int, initiative_id: int, **grantee) -> ResourceGrant:
    return ResourceGrant(
        resource_type=Tool.document.value,
        resource_id=document_id,
        initiative_id=initiative_id,
        level=grantee.pop("level", ResourceAccessLevel.read),
        **grantee,
    )


async def test_an_install_shares_what_it_owns(session, acting_user, role_session):
    install = await _install(session, acting_user, role_session, granted=_SHARES)
    s, _ = await _route(role_session, install, _SHARES)
    made = await _made_by_the_install(s, install)
    s.add(_share(made.id, install.a.id, all_initiative_members=True))
    s.add(
        _share(
            made.id,
            install.a.id,
            user_id=install.seat.user.id,
            level=ResourceAccessLevel.write,
        )
    )
    await s.flush()

    rows = (
        await s.exec(
            select(ResourceGrant.level, ResourceGrant.all_initiative_members).where(
                ResourceGrant.resource_type == Tool.document.value,
                ResourceGrant.resource_id == made.id,
                ResourceGrant.app_install_id.is_(None),
            )
        )
    ).all()
    assert sorted(rows) == [
        (ResourceAccessLevel.read, True),
        (ResourceAccessLevel.write, False),
    ]

    # And takes a share away again, while its own owner row stays.
    await s.exec(
        delete(ResourceGrant).where(
            ResourceGrant.resource_type == Tool.document.value,
            ResourceGrant.resource_id == made.id,
        )
    )
    left = (
        await s.exec(
            select(ResourceGrant.level, ResourceGrant.app_install_id).where(
                ResourceGrant.resource_type == Tool.document.value,
                ResourceGrant.resource_id == made.id,
            )
        )
    ).all()
    assert left == [(ResourceAccessLevel.owner, install.app.id)]
    await s.rollback()


@pytest.mark.parametrize(
    ("granted", "token"),
    [
        (["documents:write"], ["documents:write"]),
        (_SHARES, ["documents:write"]),
        (["documents:read", "sharing:write"], ["documents:read", "sharing:write"]),
    ],
    ids=["not_granted", "not_in_token", "no_tool_write"],
)
async def test_without_both_write_scopes_an_install_shares_nothing(
    session, acting_user, role_session, granted, token
):
    install = await _install(session, acting_user, role_session, granted=granted)
    if "documents:write" in token:
        s, _ = await _route(role_session, install, token)
        target = (await _made_by_the_install(s, install)).id
    else:
        # Owned by the install without its creating it.
        document = await create_document(session, install.a, install.seat.user)
        await route_session_to_guild(session, install.guild.id)
        await session.exec(
            delete(ResourceGrant).where(
                ResourceGrant.resource_type == Tool.document.value,
                ResourceGrant.resource_id == document.id,
            )
        )
        session.add(
            ResourceGrant(
                resource_type=Tool.document.value,
                resource_id=document.id,
                initiative_id=install.a.id,
                app_install_id=install.app.id,
                level=ResourceAccessLevel.owner,
            )
        )
        await session.commit()
        target = document.id
        s, _ = await _route(role_session, install, token)
    s.add(_share(target, install.a.id, all_initiative_members=True))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()
    await s.rollback()


async def test_reading_a_resource_is_not_enough_to_share_it(
    session, acting_user, role_session
):
    install = await _install(session, acting_user, role_session, granted=_SHARES)
    readable = await create_document(session, install.a, install.seat.user)
    await _share_with_members(session, readable, install.a.id)

    s, _ = await _route(role_session, install, _SHARES)
    assert (
        await s.exec(select(Document.id).where(Document.id == readable.id))
    ).all() == [readable.id]
    s.add(_share(readable.id, install.a.id, user_id=install.seat.user.id))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()
    await s.rollback()

    # Nor may it take the share it reads by away.
    s, _ = await _route(role_session, install, _SHARES)
    await s.exec(
        delete(ResourceGrant).where(
            ResourceGrant.resource_type == Tool.document.value,
            ResourceGrant.resource_id == readable.id,
        )
    )
    await s.commit()
    await route_session_to_guild(session, install.guild.id)
    kept = (
        await session.exec(
            select(ResourceGrant.id).where(
                ResourceGrant.resource_type == Tool.document.value,
                ResourceGrant.resource_id == readable.id,
            )
        )
    ).all()
    assert len(kept) == 2  # the seat's owner row and the members' share


@pytest.mark.parametrize("row", ["owner_for_a_person", "owner_for_itself", "to_itself"])
async def test_a_share_is_never_ownership_or_an_app_grant(
    session, acting_user, role_session, row
):
    """On a document open to its initiative for writing and owned by nobody,
    the install holds write, and still writes no owner row and no grant
    naming an app."""
    install = await _install(session, acting_user, role_session, granted=_SHARES)
    document = await create_document(session, install.a, install.seat.user)
    await route_session_to_guild(session, install.guild.id)
    await session.exec(
        delete(ResourceGrant).where(
            ResourceGrant.resource_type == Tool.document.value,
            ResourceGrant.resource_id == document.id,
        )
    )
    session.add(
        _share(
            document.id,
            install.a.id,
            all_initiative_members=True,
            level=ResourceAccessLevel.write,
        )
    )
    await session.commit()

    s, _ = await _route(role_session, install, _SHARES)
    grantee = (
        {"user_id": install.seat.user.id}
        if row == "owner_for_a_person"
        else {"app_install_id": install.app.id}
    )
    level = (
        ResourceAccessLevel.write if row == "to_itself" else ResourceAccessLevel.owner
    )
    s.add(_share(document.id, install.a.id, level=level, **grantee))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.flush()
    await s.rollback()

    # A share with a person on the same document is its to make.
    s, _ = await _route(role_session, install, _SHARES)
    s.add(_share(document.id, install.a.id, user_id=install.seat.user.id))
    await s.flush()
    await s.rollback()


async def test_a_person_shares_as_before(session, acting_user, role_session):
    """The legs leave a person's request as it was: a member of the
    initiative writes a share on a resource the database lets them reach."""
    install = await _install(session, acting_user, role_session, granted=_SHARES)
    document = await create_document(session, install.a, install.seat.user)
    person = await role_session("app_user")
    await route_as(person, user_id=install.seat.user.id, guild_id=install.guild.id)
    person.add(_share(document.id, install.a.id, all_initiative_members=True))
    await person.flush()
    await person.rollback()
