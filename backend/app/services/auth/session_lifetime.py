"""How long somebody may stay signed in before signing in again.

Two different questions, deliberately kept apart:

* ``AUTH_REFRESH_TTL_DAYS`` is how long a session may be *left alone*. Every
  rotation pushes it forward, so an app in daily use never reaches it.
* This module answers the other one — the **absolute** limit, which nothing
  pushes forward. It is what a deployment sets when it has to say "everybody
  signs in again at least this often".

The answer is stamped on the chain when the sign-in happens and carried
through every rotation unchanged, so renewing a session costs no extra read.
One consequence, and it is the right one: joining a community that asks for
the stricter standard applies at that person's next sign-in rather than
shortening the session they are in.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildMembership
from app.models.platform.guild_administration import GuildAdministration
from app.models.platform.user_token import UserToken, UserTokenPurpose
from app.services.platform import app_settings as app_settings_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


#: What a community held to the compliance standard asks of its members.
#: HIPAA's automatic-logoff expectation and NIST SP 800-63B's AAL2
#: reauthentication limit land on the same number, so one constant serves both.
COMPLIANCE_SESSION_HOURS = 12


async def _belongs_to_a_compliance_guild(
    session: AsyncSession, *, user_id: int
) -> bool:
    found = (
        await session.exec(
            select(GuildMembership.guild_id)
            .join(
                GuildAdministration,
                GuildAdministration.guild_id == GuildMembership.guild_id,
            )
            .where(
                GuildMembership.user_id == user_id,
                GuildAdministration.enforce_compliance_session.is_(True),
            )
            .limit(1)
        )
    ).first()
    return found is not None


async def resolve_max_hours(session: AsyncSession, *, user_id: int) -> int | None:
    """The absolute limit that applies to this person, in hours.

    One standard rather than a number per community, so somebody in two of them
    has an answer rather than a comparison. ``None`` means no limit was asked
    for anywhere.

    A community's standard only ever tightens. The deployment's own figure is
    free-form and may already be shorter than twelve hours, and a community
    asking for a stricter session is not a place to lengthen one.
    """
    row = await app_settings_service.get_app_settings(session)
    platform_hours = row.session_max_hours
    if not await _belongs_to_a_compliance_guild(session, user_id=user_id):
        return platform_hours
    if platform_hours is None:
        return COMPLIANCE_SESSION_HOURS
    return min(COMPLIANCE_SESSION_HOURS, platform_hours)


async def chain_deadline(
    session: AsyncSession, *, user_id: int, issued: datetime
) -> datetime | None:
    """When the chain this sign-in starts must end. ``None`` for no limit."""
    hours = await resolve_max_hours(session, user_id=user_id)
    return None if hours is None else issued + timedelta(hours=hours)


async def apply_to_device_tokens(session: AsyncSession) -> None:
    """Bring device tokens already issued under the limit now in force.

    A session carries its deadline on the row and a device token carries its
    in ``expires_at``, which is what every request already checks — so this
    writes the limit in once, when it changes, rather than making every native
    request read the policy to find out.

    Run when either control moves. A token is only ever brought *in*: this
    takes the earlier of where it stands and where the limit puts it, so it can
    shorten a window and never extend one.
    """
    row = await app_settings_service.get_app_settings(session)
    platform_hours = row.session_max_hours
    now = _now()

    if platform_hours is not None:
        await session.exec(
            update(UserToken)
            .where(
                UserToken.purpose == UserTokenPurpose.device_auth,
                UserToken.expires_at > now,
            )
            .values(
                expires_at=func.least(
                    UserToken.expires_at,
                    UserToken.created_at + timedelta(hours=platform_hours),
                )
            )
        )

    compliance_hours = (
        COMPLIANCE_SESSION_HOURS
        if platform_hours is None
        else min(COMPLIANCE_SESSION_HOURS, platform_hours)
    )
    members = (
        select(GuildMembership.user_id)
        .join(
            GuildAdministration,
            GuildAdministration.guild_id == GuildMembership.guild_id,
        )
        .where(GuildAdministration.enforce_compliance_session.is_(True))
    )
    await session.exec(
        update(UserToken)
        .where(
            UserToken.purpose == UserTokenPurpose.device_auth,
            UserToken.expires_at > now,
            UserToken.user_id.in_(members),
        )
        .values(
            expires_at=func.least(
                UserToken.expires_at,
                UserToken.created_at + timedelta(hours=compliance_hours),
            )
        )
    )
