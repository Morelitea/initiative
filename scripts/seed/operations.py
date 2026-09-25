"""The operations community: where this deployment's own security,
moderation, support and feedback work lands, set up with the platform ladder
seated in it.

The ladder is a set of accounts with nowhere of their own to work until this
exists, which is what made every intake surface unreachable on a fresh dev
database. So it is seeded as an ordinary community with the ladder mapped onto
community roles: the platform owner holds the seat (as its creator), the
operator administers it, and everybody else is a member. Both halves are set
up, because either one missing leaves the streams unreachable: the
deployment's pointer (``app_settings.operations_guild_id``) and a binding per
stream, each from its committed blueprint the way the operator's own "set this
up for me" does.
"""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import IntakeStream
from app.db.schema_provisioning import provision_guild
from app.db.session import set_rls_context
from app.models.platform.guild import Guild
from app.models.platform.user import User
from app.services.platform import intake_setup

from seed import guilds, initiatives
from seed.common import Community

#: Named for the product rather than for a company: a deployment runs one of
#: these, and what it is called is what everybody in it sees.
OPERATIONS_GUILD_NAME = "Initiative"

_OWNER = "Platform Owner"
_OPERATOR = "Platform Operator"
_MEMBERS = ["Platform Moderator", "Platform Support", "Platform Member"]


async def seed(
    session: AsyncSession, ids: dict[str, list], users: dict[str, User]
) -> Guild:
    guild = await guilds.create_guild(
        session,
        ids,
        name=OPERATIONS_GUILD_NAME,
        description="Where this deployment's security, moderation, support and feedback work lands.",
        creator=users[_OWNER],
    )
    await session.commit()
    guilds.expunge_guild_scoped(session)
    await provision_guild(guild.id)
    await guilds.add_members(
        session,
        guild,
        [users[name] for name in (_OPERATOR, *_MEMBERS)],
        admins=[users[_OPERATOR]],
    )
    await session.commit()
    await set_rls_context(session, guild_id=guild.id)
    c = Community(key="operations", session=session, ids=ids, users=users, guild=guild)
    initiative = await initiatives.create_initiative(
        c,
        "operations",
        {
            "name": "Operations",
            "description": "The deployment's own cases: security, moderation, support and feedback.",
            "color": "#dc2626",
            "pm": _OWNER,
            "members": [_OPERATOR, *_MEMBERS],
        },
    )
    await session.commit()

    await set_rls_context(session)
    await intake_setup.set_operations_guild(session, guild.id)
    await session.commit()
    for stream in IntakeStream:
        await intake_setup.provision_from_blueprint(
            session, stream=stream, initiative_id=initiative.id, importer=users[_OWNER]
        )
    # provision_from_blueprint routes into the operations guild to write the
    # binding; hand the session back at the public baseline.
    await set_rls_context(session)
    return guild
