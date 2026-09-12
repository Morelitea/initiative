"""What one webhook subscriber calls the guild, and the people writing in it.

A delivery leaves this deployment, so the guild it came from and the member
whose write caused it are named by reference rather than by row id — the same
rule every other boundary follows (``history/opaque-identity-design.md``).

Which reference depends on who is receiving, because a reference is pairwise:

* **An app registered the subscription.** It already holds a name for the guild
  and for each member, minted at its install and used on every other exchange
  it has with us. A delivery arrives under those, so the app can match an
  envelope to what it has stored without learning a second set of names for the
  same people.
* **A member registered it against a URL of their own.** There is no install to
  borrow a sector from, so the subscription is the sector. The names are stable
  for that subscription and unrelated to every other subscriber's.

Either way the ids are per-guild-schema sequences, so the sector is
``(guild_id, <thing>)`` and the purpose says which kind of thing — an install
and a subscription in one guild can both be number three.

Reached only on the system engine, like every other minting path, so each call
opens a session of its own: the callers are a background poller routed into a
guild role and a request handler doing the same.
"""

from __future__ import annotations

from collections.abc import Collection

from app.db import session as db_session
from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
from app.services.platform import identity_refs

__all__ = ["drop_subscription_refs", "name_for_subscriber"]


def _sector(
    *, guild_id: int, app_install_id: int | None, subscription_id: int
) -> tuple[IdentityPurpose, int]:
    """The purpose and the id inside the guild that this subscriber is named by."""
    if app_install_id is not None:
        return IdentityPurpose.app, app_install_id
    return IdentityPurpose.webhook, subscription_id


async def name_for_subscriber(
    *,
    guild_id: int,
    app_install_id: int | None,
    subscription_id: int,
    actor_ids: Collection[int] = (),
) -> tuple[str, dict[int, str]]:
    """This subscriber's names for the guild and for each actor it will be told about.

    Returns ``(guild_ref, {user_id: ref})``. Minted on first use, in one
    session for the whole batch, because a delivery names as many people as the
    transaction it describes touched.
    """
    purpose, sector_id = _sector(
        guild_id=guild_id,
        app_install_id=app_install_id,
        subscription_id=subscription_id,
    )
    wanted = {actor_id for actor_id in actor_ids if actor_id is not None}

    async with db_session.AdminSessionLocal() as session:
        guild_ref = await identity_refs.ensure_ref(
            session,
            entity_type=IdentityEntity.guild,
            entity_id=guild_id,
            purpose=purpose,
            sector_guild_id=guild_id,
            sector_id=sector_id,
        )
        actor_refs = {
            actor_id: await identity_refs.ensure_ref(
                session,
                entity_type=IdentityEntity.user,
                entity_id=actor_id,
                purpose=purpose,
                sector_guild_id=guild_id,
                sector_id=sector_id,
            )
            for actor_id in sorted(wanted)
        }
        await session.commit()
    return guild_ref, actor_refs


async def drop_subscription_refs(*, guild_id: int, subscription_id: int) -> int:
    """Remove the references minted for one subscription's own sector.

    Only the sector this module owns: a subscription an app registered is named
    in that app's, which outlives it and belongs to the install.
    """
    async with db_session.AdminSessionLocal() as session:
        dropped = await identity_refs.drop_sector_refs(
            session,
            sector_guild_id=guild_id,
            sector_id=subscription_id,
            purpose=IdentityPurpose.webhook,
        )
        await session.commit()
    return dropped
