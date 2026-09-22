"""Which ways in this deployment permits.

The one read of the setting, and the one write. Everything that gates a
sign-in route asks here, so the rules live in exactly one place. (A fresh
deployment's first value is the env's, ``AUTH_LOGIN_METHODS`` — seeded once
into the settings row when it is created, see
``app_settings._seeded_login_methods`` — and every change after that is
:func:`set_login_methods`.)
"""

from __future__ import annotations

from typing import Sequence

from fastapi import HTTPException, status
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.login_methods import (
    FACTOR_METHODS,
    PRIMARY_LOGIN_METHODS,
    LoginMethod,
    SecondFactorRequirement,
    methods_from_values,
)
from app.core.messages import SettingsMessages
from app.core.security import AUTH_POLICY_UNMET_HEADER
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.models.platform.user import User, UserRole, UserStatus
from app.models.platform.user_passkey import UserPasskey
from app.models.platform.user_totp import UserTotp
from app.services import audit as audit_service
from app.services import email as email_service
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
    return methods_from_values(row.login_methods)


async def resolve_login_methods(session: AsyncSession) -> frozenset[LoginMethod]:
    """The sign-in methods this deployment permits. See :func:`methods_from_row`."""
    return methods_from_row(await app_settings_service.get_app_settings(session))


async def login_method_allowed(session: AsyncSession, method: LoginMethod) -> bool:
    """Whether one method may be used to open a session right now."""
    return method in await resolve_login_methods(session)


def requirement_from_row(row: AppSetting) -> SecondFactorRequirement:
    """What this ``app_settings`` row asks of an account.

    Pure, so a caller holding the row does not fetch it twice. A value this
    version does not recognise reads as ``nobody``: the column is a database
    enum, so that can only be a row written by a later version, and asking for
    something this one cannot describe is worse than asking for nothing.
    """
    try:
        return SecondFactorRequirement(row.second_factor_requirement)
    except ValueError:
        return SecondFactorRequirement.nobody


async def second_factor_requirement(session: AsyncSession) -> SecondFactorRequirement:
    """What this deployment asks of an account. See :func:`requirement_from_row`."""
    return requirement_from_row(await app_settings_service.get_app_settings(session))


def rule_covers(level: SecondFactorRequirement, role: UserRole) -> bool:
    """Whether ``level`` asks this account for a second factor.

    The rung is the whole distinction: ``platform_roles`` means everybody above
    ``member`` on the ladder in :mod:`app.core.capabilities`, which is the one
    fact the database re-derives for itself from ``app.platform_role``.
    """
    if level is SecondFactorRequirement.everyone:
        return True
    return (
        level is SecondFactorRequirement.platform_roles and role is not UserRole.member
    )


def _holds_a_factor_clause():
    """Accounts holding a second factor: a confirmed authenticator, or a key.

    Either answers the deployment, which asks only that the account has one —
    unlike a community, which names the method it wants and reads what the
    session presented.
    """
    return (
        select(UserTotp.user_id)
        .where(UserTotp.user_id == User.id, UserTotp.confirmed_at.is_not(None))
        .exists()
        | select(UserPasskey.id).where(UserPasskey.user_id == User.id).exists()
    )


async def holds_second_factor(session: AsyncSession, *, user_id: int) -> bool:
    """Whether this account holds a second factor of its own.

    On the system engine: both credential stores are ``app_admin``-only.
    """
    return bool(
        await session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.id == user_id, _holds_a_factor_clause())
        )
    )


async def accounts_without_factor(
    session: AsyncSession, *, level: SecondFactorRequirement
) -> int:
    """How many accounts ``level`` would ask to set one up.

    Live accounts the level covers that hold neither an authenticator nor a
    key. It counts what the page states before the write, so an operator
    turning the rule on knows how many people meet it the next time they open
    the app.

    An account whose identity provider carries out the second factor is
    counted here and asked for nothing in practice: the session it arrives on
    says the factor was used, which answers the rule without a local one. The
    figure is therefore the most it could be, which is the honest direction
    for a warning.
    """
    if level is SecondFactorRequirement.nobody:
        return 0
    conditions = [User.status == UserStatus.active, ~_holds_a_factor_clause()]
    if level is SecondFactorRequirement.platform_roles:
        conditions.append(User.role != UserRole.member)
    return (
        await session.exec(select(func.count()).select_from(User).where(*conditions))
    ).one()


async def guilds_requiring_sign_in(session: AsyncSession) -> int:
    """How many guilds require a sign-in of their own.

    A requirement is enforced from the policy row alone — the gate in
    ``deps.py`` and ``public.guild_auth_satisfied()`` read nothing else — so it
    stands whatever happens to the route that satisfies it. Counted before
    single sign-on is withdrawn for that reason.

    Any row that is not ``open`` counts. A requirement names a provider, or a
    way in, or both, and a table constraint is what makes that list complete —
    so this stays right when a third thing becomes requirable, rather than
    quietly skipping it.
    """
    return (
        await session.exec(
            select(func.count())
            .select_from(GuildAuthPolicy)
            .where(GuildAuthPolicy.policy != "open")
        )
    ).one()


async def guilds_requiring_method(session: AsyncSession, method: LoginMethod) -> int:
    """How many communities ask for this particular method.

    Narrower than :func:`guilds_requiring_sign_in`, which counts every rule
    that is not open because withdrawing single sign-on can undo a rule that
    names a provider as well as one that names the method. Asking for a second
    factor is only ever named, so only the rules that name it are at stake.
    """
    return (
        await session.exec(
            select(func.count())
            .select_from(GuildAuthPolicy)
            .where(
                GuildAuthPolicy.policy != "open",
                GuildAuthPolicy.require_methods.contains([method.value]),
            )
        )
    ).one()


async def stranded_between(
    session: AsyncSession,
    *,
    current: frozenset[LoginMethod],
    requested: frozenset[LoginMethod],
) -> int:
    """How many accounts can sign in under ``current`` and could not under
    ``requested``.

    Both sets in one question, so an account holding two credentials is
    counted for the pair of methods going together as well as for either alone.

    ``totp`` never moves this figure: a second factor accompanies a sign-in
    rather than beginning one, so withdrawing it leaves every account able to
    sign in exactly as it did. What it does do is stop the factor being asked
    for, which the surface says plainly.
    """
    return await identity_service.stranded_between(
        session, current=current, requested=requested
    )


async def set_login_methods(
    session: AsyncSession,
    *,
    methods: Sequence[LoginMethod],
    acknowledge_stranded: int | None,
    actor_user_id: int | None,
) -> AppSetting:
    """Set which ways in the deployment permits.

    At least one, which the column's own constraint also holds.

    Three refusals, all 409. Permitting the emailed code asks that the
    deployment can send mail, since that is how the code reaches anybody.
    Withdrawing single sign-on while a guild requires
    one names the guilds instead: a requirement is enforced from its policy row
    and stands on its own, so it is lifted first and the withdrawal then goes
    through. And a write that leaves somebody with no way in is refused with
    the count — unless the caller acknowledges exactly that number, which is how
    an SSO-only deployment is reachable at all: some account almost always still
    holds a password, and a permanent refusal would make the posture unbuildable
    rather than safe. The figure is taken over the whole write rather than one
    method at a time, so an account holding two of the credentials being
    withdrawn is counted. The acknowledged number must match what the server
    computes now, so it cannot be sent blind or sent again once it has moved.

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
    # Not merely "something is ticked": something that can begin a session is.
    # The column's CHECK holds the same rule at the database.
    if not requested.intersection(PRIMARY_LOGIN_METHODS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.LOGIN_METHODS_NO_PRIMARY,
        )

    # Take the settings row before counting anything. A guild admin setting a
    # sign-in requirement reads this same row under a shared lock, so the two
    # transactions order rather than interleave: either this sees their new
    # requirement, or they see single sign-on already withdrawn.
    row = await _locked_settings(session)
    current = methods_from_row(row)
    withdrawn = current - requested
    added = requested - current

    # The emailed code is the one way in the deployment delivers itself, so it
    # needs somewhere to deliver from. Checked on the way up only: an operator
    # who later clears the SMTP settings is not retrospectively refused here,
    # and the send route reports it at the moment it cannot send.
    if LoginMethod.email_otp in added and not await email_service.email_configured(
        session
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=SettingsMessages.LOGIN_METHODS_NO_EMAIL,
        )

    if LoginMethod.sso in withdrawn:
        requiring = await guilds_requiring_sign_in(session)
        if requiring:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=SettingsMessages.LOGIN_METHODS_GUILD_POLICIES,
                headers={"X-Affected-Count": str(requiring)},
            )

    # The methods a community names one at a time. Withdrawing one leaves the
    # communities that ask for it with a rule nothing can answer, so the rule
    # is lifted first and the withdrawal then goes through. ``sso`` is counted
    # above instead, where a rule naming a provider counts too.
    for named in (LoginMethod.totp, LoginMethod.passkey):
        if named not in withdrawn:
            continue
        requiring = await guilds_requiring_method(session, named)
        if requiring:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=SettingsMessages.LOGIN_METHODS_GUILD_POLICIES,
                headers={"X-Affected-Count": str(requiring)},
            )

    # And the deployment's own requirement, which names no method but needs
    # one to exist. Withdrawing the last of them would leave a rule nobody new
    # could answer, so the rule is lowered first and the withdrawal then goes
    # through — the same order a community's requirement asks for.
    if withdrawn.intersection(FACTOR_METHODS) and not requested.intersection(
        FACTOR_METHODS
    ):
        if requirement_from_row(row) is not SecondFactorRequirement.nobody:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=SettingsMessages.LOGIN_METHODS_FACTOR_REQUIRED,
            )

    total_stranded = await stranded_between(
        session, current=current, requested=requested
    )

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


async def second_factor_available(session: AsyncSession) -> bool:
    """Whether this deployment offers a second factor at all.

    What a community's own requirement is offered against: with no kind of
    factor permitted here, there is nothing for anybody to be asked to hold,
    so the question is not put.
    """
    permitted = await resolve_login_methods(session)
    return any(method in permitted for method in FACTOR_METHODS)


async def _locked_settings(session: AsyncSession) -> AppSetting:
    """The settings row, held for the rest of this transaction."""
    await app_settings_service.ensure_settings_row(session)
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
    await app_settings_service.ensure_settings_row(session)
    return (
        await session.exec(
            select(AppSetting)
            .where(AppSetting.id == GLOBAL_SETTINGS_ID)
            .with_for_update(read=True)
        )
    ).one()


async def answers_the_rule(session: AsyncSession, *, user: User) -> bool:
    """Whether this request's account answers the deployment's rule.

    Two ways, and either will do: the account holds a factor of its own, or
    this session presented one — which is what an identity provider's own
    second factor looks like from here, an account holding nothing locally.

    Read fresh rather than from the request context, which the gate fills in
    only where the rule applies: a write that turns the rule *on* has to know
    the answer before there is a rule to have gated anything.
    """
    from app.core import auth_context
    from app.services.auth.assurance import SECOND_FACTOR_AMR

    if SECOND_FACTOR_AMR in auth_context.session_amr():
        return True
    return await holds_second_factor(session, user_id=user.id)


async def set_second_factor_requirement(
    session: AsyncSession,
    *,
    level: SecondFactorRequirement,
    actor: User,
) -> AppSetting:
    """Set who this deployment asks to hold a second factor.

    Two refusals, both on the way up; lowering carries neither, because it only
    ever admits more.

    A level needs something that can answer it — the deployment has to be
    permitting the authenticator app or passkeys — and the account writing it
    has to answer it already, where the level covers them. The second is the
    same "prove it before it binds anybody" a community's requirement makes,
    and here it also means the rule is written by somebody who will still be
    able to open the page afterwards.

    Nobody is signed out. An account the rule covers is asked at its next
    request and can answer it there; a credential that cannot present one —
    the app on a phone, a personal API key — works again once its owner holds
    a factor.
    """
    row = await _locked_settings(session)
    current = requirement_from_row(row)

    if level is not SecondFactorRequirement.nobody:
        permitted = methods_from_row(row)
        if not permitted.intersection(FACTOR_METHODS):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=SettingsMessages.FACTOR_REQUIREMENT_NO_METHOD,
            )
        if rule_covers(level, actor.role) and not await answers_the_rule(
            session, user=actor
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=SettingsMessages.FACTOR_REQUIREMENT_SELF_UNSATISFIED,
                headers={AUTH_POLICY_UNMET_HEADER: LoginMethod.totp.value},
            )

    row.second_factor_requirement = level
    session.add(row)
    await audit_service.record(
        session,
        event_type=AuditEventType.PLATFORM_SECOND_FACTOR_REQUIREMENT_CHANGED,
        actor_user_id=actor.id,
        detail={"from": current.value, "to": level.value},
    )
    await session.commit()
    await session.refresh(row)
    return row
