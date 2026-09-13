"""Which name a webhook subscriber is given for a guild, and why that one.

The rule has one branch, and both sides of it matter. An app that registered a
subscription already knows this guild and these people — it was told at its
install, and every other exchange it has with us uses those names. A delivery
has to arrive under the same ones, or the app is holding two unrelated values
for one guild and can match an envelope to nothing.

A member registering a URL of their own has no install to borrow from, so the
subscription is its own sector.
"""

from __future__ import annotations

import pytest

from app.models.platform.identity_ref import IdentityPurpose
from app.services.marketplace.app_refs import ensure_app_guild_ref, ensure_app_ref
from app.services.tenant import webhook_refs
from app.testing import create_guild, create_user

pytestmark = pytest.mark.integration


async def test_an_app_hears_the_names_it_already_holds(session):
    """The whole point of the branch. The app channel minted these at install;
    a delivery repeats them rather than introducing a second set."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    install_id = 4242

    guild_ref, actor_refs = await webhook_refs.name_for_subscriber(
        guild_id=guild.id,
        app_install_id=install_id,
        subscription_id=1,
        actor_ids=(user.id,),
    )

    assert guild_ref == await ensure_app_guild_ref(
        guild_id=guild.id, app_install_id=install_id
    )
    assert actor_refs[user.id] == await ensure_app_ref(
        guild_id=guild.id, app_install_id=install_id, user_id=user.id
    )


async def test_a_member_registered_target_is_named_by_its_subscription(session):
    """No install to borrow a sector from, so the subscription is one."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)

    guild_ref, actor_refs = await webhook_refs.name_for_subscriber(
        guild_id=guild.id,
        app_install_id=None,
        subscription_id=7,
        actor_ids=(user.id,),
    )

    assert guild_ref.startswith("g" + IdentityPurpose.webhook.code + "_")
    assert actor_refs[user.id].startswith("u" + IdentityPurpose.webhook.code + "_")
    assert guild_ref != await ensure_app_guild_ref(guild_id=guild.id, app_install_id=7)


async def test_two_subscriptions_in_one_guild_are_unrelated(session):
    """Two targets comparing notes learn nothing about each other's guild."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)

    first, first_actors = await webhook_refs.name_for_subscriber(
        guild_id=guild.id, app_install_id=None, subscription_id=1, actor_ids=(user.id,)
    )
    second, second_actors = await webhook_refs.name_for_subscriber(
        guild_id=guild.id, app_install_id=None, subscription_id=2, actor_ids=(user.id,)
    )

    assert first != second
    assert first_actors[user.id] != second_actors[user.id]


async def test_the_same_subscription_is_named_the_same_way_twice(session):
    """Minted on first use and then stable — a receiver stores it."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)

    first, _ = await webhook_refs.name_for_subscriber(
        guild_id=guild.id, app_install_id=None, subscription_id=1
    )
    again, _ = await webhook_refs.name_for_subscriber(
        guild_id=guild.id, app_install_id=None, subscription_id=1
    )

    assert first == again


async def test_dropping_a_subscription_leaves_an_install_alone(session):
    """A subscription and an install in one guild can both be number three —
    the ids are per-guild-schema sequences. The purpose is what separates the
    two sectors, and deleting one must not take the other's names with it."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    shared_id = 3

    own, _ = await webhook_refs.name_for_subscriber(
        guild_id=guild.id, app_install_id=None, subscription_id=shared_id
    )
    borrowed = await ensure_app_guild_ref(guild_id=guild.id, app_install_id=shared_id)

    dropped = await webhook_refs.drop_subscription_refs(
        guild_id=guild.id, subscription_id=shared_id
    )

    assert dropped == 1
    assert (
        await ensure_app_guild_ref(guild_id=guild.id, app_install_id=shared_id)
        == borrowed
    )
    fresh, _ = await webhook_refs.name_for_subscriber(
        guild_id=guild.id, app_install_id=None, subscription_id=shared_id
    )
    assert fresh != own
