"""Apps calling apps: Initiative is the hub.

An installed app never addresses another app. It asks Initiative, on its own
installation or member token, to call one of the other app's public endpoints
in the same community, and Initiative makes the call the way it makes one for a
widget (:func:`app.services.marketplace.app_data._call_app`), with a context
token that names the calling app (``act``), whose behalf the call is on
(``actor``), the member by the called app's own reference for them
(``member``), and the initiative the caller is confined to.

The checks, in order, each with its own refusal:

1. the caller's token is live (the install seam, before this module runs);
2. ``apps:<target>`` is in the token's scopes, the seat's grant and what the
   caller's pinned version requests (``insufficient_scope``);
3. the target is installed, switched on and live in the same community
   (``target_not_installed``);
4. the endpoint is public (``endpoint_not_public``);
5. the endpoint takes the actor: ``installation`` for an installation token,
   ``member`` for a member token (``actor_not_supported``);
6. a caller confined to an initiative finds the target placed there too
   (``target_not_placed``);
7. a member token's member is named to the target by the target's own
   reference, which the caller never sees.

A read goes through the widget path's response cache, keyed also by the
caller, the actor, the member's reference and the initiative. A write is never
cached and never retried.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import httpx
from sqlalchemy import or_, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.app_scopes import app_scope
from app.core.messages import AppDataMessages, AppHubMessages
from app.db.guild_standing import ISSUABLE_SCOPES_SQL
from app.db.session import clear_rls_context, set_rls_context
from app.models.tenant.app_member_consent import AppMemberConsent, ConsentAccess
from app.models.tenant.app_placement import AppPlacement
from app.models.tenant.guild_app import GuildApp
from app.services.marketplace import app_data
from app.services.marketplace.app_data import AppDataError, CallingApp
from app.services.marketplace.app_refs import ensure_app_ref
from app.services.marketplace.registration_lookup import RegistrationSnapshot
from app.services.marketplace.service_apps import is_admin_only
from app.services.tenant.app_channels import owns_install

__all__ = [
    "INSTALLATION",
    "MEMBER",
    "HubAnswer",
    "HubCaller",
    "call_app",
]

#: The two actors a call can be on behalf of: the community, or one member.
INSTALLATION = "installation"
MEMBER = "member"

#: The directions a caller may invoke. An emission is delivered, not called.
_CALLABLE_DIRECTIONS = frozenset({"read", "write"})


@dataclass(frozen=True)
class HubCaller:
    """The app asking, as its admitted token names it."""

    guild_id: int
    install_id: int
    #: The calling app's public id.
    client_id: str
    token_scopes: frozenset[str]
    #: The initiative the token is confined to, when it is.
    initiative_id: Optional[int] = None
    #: The member a member token acts for, and the purpose they consented to.
    member_user_id: Optional[int] = None
    purpose: Optional[str] = None

    @property
    def actor(self) -> str:
        return MEMBER if self.member_user_id is not None else INSTALLATION


@dataclass(frozen=True)
class HubAnswer:
    """What the app called answered, as it answered it."""

    body: dict[str, Any]
    #: ``read`` or ``write``.
    direction: str
    #: The answer came from the response cache.
    cached: bool = False


_ISSUABLE_SQL = text(
    f"SELECT {ISSUABLE_SCOPES_SQL} FROM guild_apps a WHERE a.id = :install_id"
)


def _refuse(code: str, status_code: int) -> AppDataError:
    return AppDataError(code, status_code)


def _callable_endpoint(
    definition: Mapping[str, Any] | None, endpoint_id: str
) -> Optional[dict[str, Any]]:
    """One endpoint of the pinned definition a caller may invoke, or None."""
    declared = (definition or {}).get("endpoints")
    for endpoint in declared if isinstance(declared, list) else []:
        if (
            isinstance(endpoint, dict)
            and endpoint.get("id") == endpoint_id
            and endpoint.get("direction") in _CALLABLE_DIRECTIONS
        ):
            return endpoint
    return None


async def _target_registration(public_id: str) -> RegistrationSnapshot:
    """The target's registration, live, or ``target_not_installed``."""
    try:
        return await app_data._load_registration(public_id)
    except AppDataError as exc:
        raise _refuse(AppHubMessages.TARGET_NOT_INSTALLED, 404) from exc


async def _consent_writes(session: AsyncSession, caller: HubCaller) -> bool:
    """Whether the member a member token acts for let the caller write as
    them, by the consent the token was issued on."""
    consent = (
        await session.exec(
            select(AppMemberConsent.granted_access).where(
                AppMemberConsent.install_id == caller.install_id,
                AppMemberConsent.user_id == caller.member_user_id,
                AppMemberConsent.purpose.is_not_distinct_from(caller.purpose),
                AppMemberConsent.granted_access.is_not(None),
                AppMemberConsent.revoked_at.is_(None),
                or_(
                    AppMemberConsent.initiative_id.is_(None),
                    AppMemberConsent.initiative_id == caller.initiative_id,
                ),
            )
        )
    ).first()
    return consent == ConsentAccess.read_write.value


async def _placed(session: AsyncSession, install_id: int, initiative_id: int) -> bool:
    return (
        await session.exec(
            select(AppPlacement.install_id).where(
                AppPlacement.install_id == install_id,
                AppPlacement.initiative_id == initiative_id,
            )
        )
    ).first() is not None


def _hub_cache_key(base: str, caller: HubCaller, member_ref: Optional[str]) -> str:
    """The widget path's key, with everything else the answer may depend on:
    who called, on whose behalf, and where."""
    return (
        f"{base}:hub:{caller.client_id}:{caller.actor}:"
        f"{member_ref or ''}:{caller.initiative_id or ''}"
    )


async def call_app(
    session: AsyncSession,
    caller: HubCaller,
    *,
    target_public_id: str,
    endpoint_id: str,
    params: Mapping[str, Any],
    transport: httpx.AsyncBaseTransport | None = None,
) -> HubAnswer:
    """Check one call against checks 2–7 and make it.

    ``session`` is a system-engine session from the caller's community's
    cohort, as ``get_system_session`` hands one to an installation token's
    request. It is routed into that community here, read-only, and left
    unrouted and rolled back afterwards.
    Raises :class:`AppDataError` with the refusal's code and status.
    """
    scope = app_scope(target_public_id)
    if scope not in caller.token_scopes:
        raise _refuse(AppHubMessages.INSUFFICIENT_SCOPE, 403)

    try:
        await set_rls_context(session, guild_id=caller.guild_id, read_only=True)
        # Read now, so a scope the seat has taken back refuses the next call.
        issuable = (
            await session.exec(_ISSUABLE_SQL, params={"install_id": caller.install_id})
        ).scalar_one_or_none()
        if issuable is None or scope not in issuable:
            raise _refuse(AppHubMessages.INSUFFICIENT_SCOPE, 403)

        registration = await _target_registration(target_public_id)
        target = (
            (
                await session.exec(
                    select(GuildApp).where(
                        GuildApp.listing_uid == registration.listing_uid
                    )
                )
            ).first()
            if registration.listing_uid
            else None
        )
        if (
            target is None
            or target.id == caller.install_id
            or not owns_install(target, registration)
            or not target.enabled
        ):
            raise _refuse(AppHubMessages.TARGET_NOT_INSTALLED, 404)

        endpoint = _callable_endpoint(target.definition, endpoint_id)
        if endpoint is None:
            raise _refuse(AppDataMessages.ENDPOINT_NOT_FOUND, 404)
        # An endpoint for the community's admins alone is not offered to apps.
        if endpoint.get("public") is not True or is_admin_only(endpoint):
            raise _refuse(AppHubMessages.ENDPOINT_NOT_PUBLIC, 403)

        actors = endpoint.get("actors")
        if caller.actor not in (actors if isinstance(actors, list) else []):
            raise _refuse(AppHubMessages.ACTOR_NOT_SUPPORTED, 403)
        direction = str(endpoint["direction"])
        if (
            caller.actor == MEMBER
            and direction == "write"
            and not await _consent_writes(session, caller)
        ):
            raise _refuse(AppHubMessages.INSUFFICIENT_SCOPE, 403)

        if caller.initiative_id is not None and not await _placed(
            session, int(target.id or 0), caller.initiative_id
        ):
            raise _refuse(AppHubMessages.TARGET_NOT_PLACED, 403)

        values, canonical = app_data.validate_params(
            endpoint, json.dumps(dict(params)) if params else None
        )
        refs = await app_data._resolve_connections(
            session,
            app=target,
            endpoint=endpoint,
            user_id=caller.member_user_id,
            actor=caller.actor,
        )
    finally:
        # What was read stays readable once the transaction ends.
        session.expunge_all()
        clear_rls_context(session)
        await session.rollback()

    target_id = int(target.id or 0)
    member_user_id = caller.member_user_id
    member_ref = (
        await ensure_app_ref(
            guild_id=caller.guild_id, app_install_id=target_id, user_id=member_user_id
        )
        if member_user_id is not None
        else None
    )
    calling = CallingApp(
        public_id=caller.client_id,
        actor=caller.actor,
        member_ref=member_ref,
        initiative_id=caller.initiative_id,
    )

    async def read(request: httpx.Request) -> dict[str, Any]:
        return await app_data._read_body(request, transport=transport)

    async def call() -> dict[str, Any]:
        return await app_data._call_app(
            registration=registration,
            app=target,
            guild_id=caller.guild_id,
            endpoint_id=endpoint_id,
            params=values,
            refs=refs,
            transport=transport,
            read=read,
            caller=calling,
        )

    if direction != "read":
        return HubAnswer(body=await call(), direction=direction)

    key = _hub_cache_key(
        app_data._cache_key(
            guild_id=caller.guild_id,
            app=target,
            endpoint_id=endpoint_id,
            canonical_params=canonical,
            refs=refs,
        ),
        caller,
        member_ref,
    )
    body, cached = await app_data.cached_call(
        key, app_data._effective_ttl(endpoint), call
    )
    return HubAnswer(body=body, direction=direction, cached=cached)
