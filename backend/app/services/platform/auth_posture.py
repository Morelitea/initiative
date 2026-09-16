"""Which ways in this deployment permits.

The one read of the setting, and the one write. Everything that gates a
sign-in route asks here, so the rules live in exactly one place.
"""

from __future__ import annotations

from typing import Sequence

from fastapi import HTTPException, status
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.login_methods import DEFAULT_LOGIN_METHODS, LoginMethod
from app.core.messages import SettingsMessages
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.services import audit as audit_service
from app.services.auth import identity as identity_service
from app.services.platform import app_settings as app_settings_service
from app.services.platform.app_settings import GLOBAL_SETTINGS_ID


def methods_from_row(row: AppSetting) -> frozenset[LoginMethod]:
    """The sign-in methods one ``app_settings`` row permits.

    Never empty. The column is constrained non-empty and the write path refuses
    to empty it; should this read one anyway, it resolves to the default set.
    Conservative for a *gate* and conservative for an *account* point opposite
    ways here, and this resolves in the account's favour.

    Pure, so a caller that already holds the settings row does not fetch it
    twice; :func:`resolve_login_methods` is the form for callers that do not.
    """
    resolved = set()
    for value in row.login_methods or ():
        try:
            resolved.add(LoginMethod(value))
        except ValueError:
            continue
    return frozenset(resolved) or frozenset(DEFAULT_LOGIN_METHODS)


async def resolve_login_methods(session: AsyncSession) -> frozenset[LoginMethod]:
    """The sign-in methods this deployment permits. See :func:`methods_from_row`."""
    return methods_from_row(await app_settings_service.get_app_settings(session))


async def login_method_allowed(session: AsyncSession, method: LoginMethod) -> bool:
    """Whether one method may be used to open a session right now."""
    return method in await resolve_login_methods(session)


async def guilds_requiring_sign_in(session: AsyncSession) -> int:
    """How many guilds require a sign-in through a provider of their own.

    A requirement is enforced from the policy row alone — the gate in
    ``deps.py`` and ``public.guild_auth_satisfied()`` read nothing else — so it
    stands whatever happens to the route that satisfies it. Counted before
    single sign-on is withdrawn for that reason.
    """
    return (
        await session.exec(
            select(func.count())
            .select_from(GuildAuthPolicy)
            .where(
                GuildAuthPolicy.policy != "open",
                GuildAuthPolicy.provider_id.is_not(None),
            )
        )
    ).one()


async def stranded_by_withdrawing(session: AsyncSession, method: LoginMethod) -> int:
    """How many accounts could sign in today and could not without ``method``."""
    if method is LoginMethod.password:
        return await identity_service.password_only_user_count(session)
    if method is LoginMethod.sso:
        return await identity_service.federated_only_user_count(session)
    return 0


async def set_login_methods(
    session: AsyncSession,
    *,
    methods: Sequence[LoginMethod],
    acknowledge_stranded: int | None,
    actor_user_id: int | None,
) -> AppSetting:
    """Set which ways in the deployment permits.

    At least one, which the column's own constraint also holds.

    Two refusals, both 409. Withdrawing single sign-on while a guild requires
    one names the guilds instead: a requirement is enforced from its policy row
    and stands on its own, so it is lifted first and the withdrawal then goes
    through. And withdrawing a method that is somebody's only way in is
    refused with the count — unless the caller acknowledges exactly that
    number, which is how an SSO-only deployment is reachable at all: some
    account almost always still holds a password, and a permanent refusal would
    make the posture unbuildable rather than safe. The acknowledged figure must
    match what the server computes now, so it cannot be sent blind or replayed
    after the number has moved.

    Withdrawing a method signs nobody out. Sessions already open live to their
    own expiry, and device tokens and API keys are untouched — they are
    credentials derived from a sign-in that already happened, not ways in.
    """
    requested = frozenset(methods)
    if not requested:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.LOGIN_METHODS_EMPTY,
        )

    # Take the settings row before counting anything. A guild admin setting a
    # sign-in requirement reads this same row under a shared lock, so the two
    # transactions order rather than interleave: either this sees their new
    # requirement, or they see single sign-on already withdrawn.
    row = await _locked_settings(session)
    current = methods_from_row(row)
    withdrawn = current - requested

    if LoginMethod.sso in withdrawn:
        requiring = await guilds_requiring_sign_in(session)
        if requiring:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=SettingsMessages.LOGIN_METHODS_GUILD_POLICIES,
                headers={"X-Affected-Count": str(requiring)},
            )

    total_stranded = 0
    for method in sorted(withdrawn, key=lambda m: m.value):
        total_stranded += await stranded_by_withdrawing(session, method)

    if total_stranded:
        if acknowledge_stranded is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=SettingsMessages.LOGIN_METHODS_WOULD_STRAND,
                headers={"X-Affected-Count": str(total_stranded)},
            )
        if acknowledge_stranded != total_stranded:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=SettingsMessages.LOGIN_METHODS_STALE_ACKNOWLEDGEMENT,
                headers={"X-Affected-Count": str(total_stranded)},
            )

    row.login_methods = sorted(m.value for m in requested)
    session.add(row)
    await audit_service.record(
        session,
        event_type=AuditEventType.PLATFORM_LOGIN_METHODS_CHANGED,
        actor_user_id=actor_user_id,
        detail={
            "from": sorted(m.value for m in current),
            "to": sorted(m.value for m in requested),
            "acknowledged_stranded": total_stranded or None,
        },
    )
    await session.commit()
    await session.refresh(row)
    return row


async def _locked_settings(session: AsyncSession) -> AppSetting:
    """The settings row, held for the rest of this transaction."""
    await app_settings_service.get_app_settings(session)
    return (
        await session.exec(
            select(AppSetting)
            .where(AppSetting.id == GLOBAL_SETTINGS_ID)
            .with_for_update()
        )
    ).one()


async def hold_settings_for_read(session: AsyncSession) -> AppSetting:
    """The settings row under a shared lock, for a write that depends on what it
    says staying true until that write commits.

    Shared locks do not block each other, so concurrent guild admins proceed
    normally; only a write to this row waits.
    """
    await app_settings_service.get_app_settings(session)
    return (
        await session.exec(
            select(AppSetting)
            .where(AppSetting.id == GLOBAL_SETTINGS_ID)
            .with_for_update(read=True)
        )
    ).one()
