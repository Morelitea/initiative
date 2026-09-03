"""The direct-message rule, exercised through the SQL that is its only copy.

Every case here calls ``public.dm_can_ask`` / ``dm_apparent_permission`` /
``dm_listable_in_guild`` rather than a Python restatement of them, because the
functions are the rule: a test that agreed with a mirror would prove nothing
about what the request path actually gets.
"""

import pytest
from sqlalchemy import text

from app.models.platform.contact_grant import (
    ContactGrant,
    ContactGrantKind,
    ContactGrantState,
    canonical_pair,
)
from app.models.platform.user_dm_settings import DmPolicy, UserDmSettings
from app.models.platform.user_dm_guild_optout import UserDmGuildOptout
from app.models.platform.user_ignore import UserIgnore
from app.testing import create_guild, create_guild_membership, create_user

pytestmark = pytest.mark.asyncio


async def _policy(session, user, policy: DmPolicy) -> None:
    row = await session.get(UserDmSettings, user.id)
    if row is None:
        row = UserDmSettings(user_id=user.id)
        session.add(row)
    row.dm_policy = policy
    await session.flush()


async def _grant(
    session, a, b, kind: ContactGrantKind, state=ContactGrantState.accepted
):
    low, high = canonical_pair(a.id, b.id)
    session.add(
        ContactGrant(
            user_id_low=low,
            user_id_high=high,
            kind=kind,
            state=state,
            requested_by=a.id,
        )
    )
    await session.flush()


async def _can_ask(session, frm, to) -> bool:
    return (
        await session.exec(
            text("SELECT public.dm_can_ask(:f, :t)").bindparams(f=frm.id, t=to.id)
        )
    ).scalar_one()


async def _permission(session, actor, target) -> str:
    await session.exec(
        text("SELECT set_config('app.current_user_id', :v, true)").bindparams(
            v=str(actor.id)
        )
    )
    return (
        await session.exec(
            text("SELECT public.dm_apparent_permission(:t)").bindparams(t=target.id)
        )
    ).scalar_one()


async def _listable(session, viewer, guild) -> set[int]:
    await session.exec(
        text("SELECT set_config('app.current_user_id', :v, true)").bindparams(
            v=str(viewer.id)
        )
    )
    rows = await session.exec(
        text("SELECT public.dm_listable_in_guild(:g)").bindparams(g=guild.id)
    )
    return {row[0] for row in rows}


# ---------------------------------------------------------------- can_ask ---


async def test_public_may_be_asked_by_a_stranger(session):
    asker = await create_user(session)
    target = await create_user(session)
    await _policy(session, target, DmPolicy.public)
    assert await _can_ask(session, asker, target) is True


async def test_private_may_not_be_asked_without_a_connection(session):
    asker = await create_user(session)
    target = await create_user(session)
    await _policy(session, target, DmPolicy.private)
    assert await _can_ask(session, asker, target) is False


async def test_a_connection_satisfies_private(session):
    asker = await create_user(session)
    target = await create_user(session)
    await _policy(session, target, DmPolicy.private)
    await _grant(session, asker, target, ContactGrantKind.connection)
    assert await _can_ask(session, asker, target) is True


async def test_a_pending_connection_satisfies_nothing(session):
    asker = await create_user(session)
    target = await create_user(session)
    await _policy(session, target, DmPolicy.private)
    await _grant(
        session, asker, target, ContactGrantKind.connection, ContactGrantState.pending
    )
    assert await _can_ask(session, asker, target) is False


async def test_community_needs_a_shared_community(session):
    guild = await create_guild(session)
    member = await create_user(session)
    await create_guild_membership(session, user=member, guild=guild)
    target = await create_user(session)
    await create_guild_membership(session, user=target, guild=guild)
    stranger = await create_user(session)
    await _policy(session, target, DmPolicy.community)

    assert await _can_ask(session, member, target) is True
    assert await _can_ask(session, stranger, target) is False


async def test_a_switched_off_community_does_not_count(session):
    guild = await create_guild(session)
    member = await create_user(session)
    await create_guild_membership(session, user=member, guild=guild)
    target = await create_user(session)
    await create_guild_membership(session, user=target, guild=guild)
    await _policy(session, target, DmPolicy.community)
    session.add(UserDmGuildOptout(user_id=target.id, guild_id=guild.id))
    await session.flush()

    assert await _can_ask(session, member, target) is False


async def test_another_shared_community_still_counts(session):
    off = await create_guild(session)
    on = await create_guild(session)
    member = await create_user(session)
    target = await create_user(session)
    for guild in (off, on):
        await create_guild_membership(session, user=member, guild=guild)
        await create_guild_membership(session, user=target, guild=guild)
    await _policy(session, target, DmPolicy.community)
    session.add(UserDmGuildOptout(user_id=target.id, guild_id=off.id))
    await session.flush()

    assert await _can_ask(session, member, target) is True


async def test_a_missing_settings_row_reads_as_private(session):
    asker = await create_user(session)
    target = await create_user(session)
    await session.exec(
        text("DELETE FROM public.user_dm_settings WHERE user_id = :u").bindparams(
            u=target.id
        )
    )
    assert await _can_ask(session, asker, target) is False


# ------------------------------------------------------------- permission ---


async def test_a_connection_alone_is_may_request_not_open(session):
    a = await create_user(session)
    b = await create_user(session)
    await _policy(session, a, DmPolicy.private)
    await _policy(session, b, DmPolicy.private)
    await _grant(session, a, b, ContactGrantKind.connection)

    assert await _permission(session, a, b) == "may_request"


async def test_an_accepted_message_grant_opens_it(session):
    a = await create_user(session)
    b = await create_user(session)
    await _policy(session, a, DmPolicy.private)
    await _policy(session, b, DmPolicy.private)
    await _grant(session, a, b, ContactGrantKind.connection)
    await _grant(session, a, b, ContactGrantKind.message)

    assert await _permission(session, a, b) == "open"


async def test_a_private_account_holds_nothing_without_a_connection(session):
    """The mutual half: b is public, but a is private and they are not
    connected, so neither may ask."""
    a = await create_user(session)
    b = await create_user(session)
    await _policy(session, a, DmPolicy.private)
    await _policy(session, b, DmPolicy.public)

    assert await _can_ask(session, a, b) is True
    assert await _can_ask(session, b, a) is False
    assert await _permission(session, a, b) == "denied"


async def test_an_unconfirmed_age_denies_in_both_directions(session):
    a = await create_user(session, age_confirmed_at=None)
    b = await create_user(session)
    await _policy(session, a, DmPolicy.public)
    await _policy(session, b, DmPolicy.public)
    await _grant(session, a, b, ContactGrantKind.connection)
    await _grant(session, a, b, ContactGrantKind.message)

    assert await _permission(session, a, b) == "denied"
    assert await _permission(session, b, a) == "denied"


async def test_being_ignored_does_not_change_the_answer(session):
    """The oracle guard: the same response before and after being ignored."""
    a = await create_user(session)
    b = await create_user(session)
    await _policy(session, a, DmPolicy.public)
    await _policy(session, b, DmPolicy.public)

    before = await _permission(session, a, b)
    session.add(UserIgnore(user_id=b.id, ignored_user_id=a.id))
    await session.flush()
    after = await _permission(session, a, b)

    assert before == after == "may_request"


async def test_the_permission_refuses_to_answer_without_a_caller(session):
    target = await create_user(session)
    await session.exec(text("SELECT set_config('app.current_user_id', '', true)"))
    with pytest.raises(Exception, match="app.current_user_id"):
        await session.exec(
            text("SELECT public.dm_apparent_permission(:t)").bindparams(t=target.id)
        )


# --------------------------------------------------------------- listable ---


async def test_a_private_viewer_lists_nobody_they_are_not_connected_to(session):
    guild = await create_guild(session)
    viewer = await create_user(session)
    other = await create_user(session)
    friend = await create_user(session)
    for user in (viewer, other, friend):
        await create_guild_membership(session, user=user, guild=guild)
        await _policy(session, user, DmPolicy.community)
    await _policy(session, viewer, DmPolicy.private)
    await _grant(session, viewer, friend, ContactGrantKind.connection)

    assert await _listable(session, viewer, guild) == {friend.id}


async def test_an_ignored_account_still_lists_the_person_ignoring_them(session):
    guild = await create_guild(session)
    ada = await create_user(session)
    bram = await create_user(session)
    for user in (ada, bram):
        await create_guild_membership(session, user=user, guild=guild)
        await _policy(session, user, DmPolicy.community)

    session.add(UserIgnore(user_id=ada.id, ignored_user_id=bram.id))
    await session.flush()

    assert await _listable(session, bram, guild) == {ada.id}
    assert await _listable(session, ada, guild) == set()
