"""Where sign-in is configured for this deployment, and which ways in it permits.

The one read of both settings. Everything that gates on posture or on a login
method asks here, so the precedence rule below lives in exactly one place.
"""

from __future__ import annotations

from typing import Sequence

from fastapi import HTTPException, status
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.config import AuthScope, settings
from app.core.messages import SettingsMessages
from app.core.login_methods import DEFAULT_LOGIN_METHODS, LoginMethod
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.services import audit as audit_service
from app.services.auth import identity as identity_service
from app.services.platform import app_settings as app_settings_service


def scope_from_row(row: AppSetting) -> AuthScope:
    """The posture one ``app_settings`` row expresses.

    The stored value wins when there is one; ``NULL`` means nobody has chosen
    in the settings UI and the deploy-time ``AUTH_SCOPE`` env value governs.

    That ordering is what lets this column be added to a running deployment: an
    install configured by env keeps its posture until somebody deliberately
    changes it here, so an upgrade cannot move an instance between postures.
    An unrecognised stored value resolves to the env value rather than
    raising: a posture read sits on the login path, where resolving to a known
    value is the useful behaviour.

    Pure, so a caller that already holds the settings row does not fetch it
    twice; :func:`resolve_auth_scope` is the form for callers that do not.
    """
    stored = (row.auth_scope or "").strip()
    if not stored:
        return settings.AUTH_SCOPE
    try:
        return AuthScope(stored)
    except ValueError:
        return settings.AUTH_SCOPE


def methods_from_row(row: AppSetting) -> frozenset[LoginMethod]:
    """The sign-in methods one ``app_settings`` row permits.

    Never empty. The column is constrained non-empty and the write path refuses
    to empty it; should this read one anyway, it resolves to the default set.
    Conservative for a *gate* and conservative for an *account* point opposite
    ways here, and this resolves in the account's favour.
    """
    resolved = set()
    for value in row.login_methods or ():
        try:
            resolved.add(LoginMethod(value))
        except ValueError:
            continue
    return frozenset(resolved) or frozenset(DEFAULT_LOGIN_METHODS)


async def resolve_auth_scope(session: AsyncSession) -> AuthScope:
    """The posture in force. See :func:`scope_from_row`."""
    return scope_from_row(await app_settings_service.get_app_settings(session))


async def resolve_login_methods(session: AsyncSession) -> frozenset[LoginMethod]:
    """The sign-in methods this deployment permits. See :func:`methods_from_row`."""
    return methods_from_row(await app_settings_service.get_app_settings(session))


async def login_method_allowed(session: AsyncSession, method: LoginMethod) -> bool:
    """Whether one method may be used to open a session right now."""
    return method in await resolve_login_methods(session)


async def guilds_requiring_sign_in(session: AsyncSession) -> int:
    """How many guilds require a sign-in of their own.

    A requirement is enforced from the policy row alone — the gate in
    ``deps.py`` and ``public.guild_auth_satisfied()`` read nothing else — so it
    outlives a change of posture, while the provider that satisfies it stops
    answering. Counted before a switch to platform posture for that reason.
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


async def set_auth_scope(
    session: AsyncSession,
    *,
    scope: AuthScope,
    actor_user_id: int | None,
) -> AppSetting:
    """Pin the deployment's login posture, or refuse and say what stands in the way.

    Two refusals, both 409, and both only in the direction of platform posture
    — that is the direction which withdraws a way in. Moving to guild posture
    withdraws nothing: operator-global providers answer logins in both
    postures, and a guild-scoped provider is unreachable under platform posture
    anyway.

    Writing the value also ends the deployment's reliance on the ``AUTH_SCOPE``
    env value; from here the stored one governs.
    """
    row = await app_settings_service.get_app_settings(session)
    current = scope_from_row(row)

    if scope == AuthScope.platform and current != AuthScope.platform:
        requiring = await guilds_requiring_sign_in(session)
        if requiring:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=SettingsMessages.AUTH_SCOPE_GUILD_POLICIES,
                headers={"X-Affected-Count": str(requiring)},
            )
        stranded = await identity_service.guild_provider_only_user_count(session)
        if stranded:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=SettingsMessages.AUTH_SCOPE_WOULD_STRAND,
                headers={"X-Affected-Count": str(stranded)},
            )

    row.auth_scope = scope.value
    session.add(row)
    await audit_service.record(
        session,
        event_type=AuditEventType.PLATFORM_AUTH_SCOPE_CHANGED,
        actor_user_id=actor_user_id,
        detail={"from": current.value, "to": scope.value},
    )
    await session.commit()
    await session.refresh(row)
    return row


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

    At least one, which the column's own constraint also holds. Withdrawing a
    method that is somebody's only way in is refused (409) with the count —
    unless the caller acknowledges exactly that number, which is how an
    SSO-only deployment is reachable at all: some account almost always still
    holds a password, and a permanent refusal would make the posture
    unbuildable rather than safe. The acknowledged figure must match what the
    server computes now, so it cannot be sent blind or replayed after the
    number has moved.

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

    row = await app_settings_service.get_app_settings(session)
    current = methods_from_row(row)

    withdrawn = current - requested
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
