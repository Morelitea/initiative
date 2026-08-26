"""External data reaching a widget: the proxy behind the ``app`` binding.

A widget never names an endpoint. It names a *endpoint* on an installed app, and
this module turns that into one bounded call to the app's own service and hands
back rows. Everything the call needs — where the app lives, which credentials it
may use, how long an answer is good for — comes from state the guild and the
operator already own, never from the request.

**Authorization happens before this module caches anything.** The endpoint runs
under the caller's own guild session, so the install row is reachable only from
inside that guild and a guild admin's wider reach is inherited rather than
re-implemented. What is left here is the app-shaped part of the decision: the
endpoint's declared visibility, the two kill switches (the guild's install and the
operator's registration), and whether the credentials the endpoint declared it
needs are actually present.

**The cache key contains every credential the response depended on.** That is
the whole rule, and it is what makes a stored body safe to replay:

* the guild, the install, and the pinned listing version — an entry is
  unreachable from a session that is not already inside that guild;
* the endpoint and its parameters;
* a fingerprint of the install's stored configuration, so rotating a credential
  retires the answers it produced;
* the opaque handles of every per-member connection the call used, so two
  members with different vendor accounts never share an entry while one
  member's repeated widgets and open tabs still collapse to a single fetch.

**Two bounds keep one app from costing everyone else.** Calls for the same key
are coalesced, so twenty viewers of a dashboard are one upstream request; and a
per-worker in-flight cap per app means a service that stops answering ties up a
fixed number of connections rather than the pool.

The response is passed through as rows. Nothing here reads inside them: they are
the app's data, on their way to a sandboxed widget that will be handed them as
values.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import AppDataMessages, AppServiceMessages, GuildAppMessages
from app.core.security import (
    AppPlatformSigningNotConfiguredError,
    app_platform_signing_enabled,
)
from app.db import session as db_session
from app.models.platform.app_service_registration import (
    AppServiceRegistration,
    is_live,
)
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.guild_app_user_connection import GuildAppUserConnection
from app.services.marketplace.context_jwt import mint_context_token
from app.services.marketplace.service_apps import clears_visibility
from app.services.safe_http import build_validated_request
from app.services.tenant import app_config as app_config_service
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_INFLIGHT_PER_APP",
    "MAX_PARAMS_BYTES",
    "MAX_RESPONSE_BYTES",
    "MAX_CACHE_TTL_SECONDS",
    "REQUEST_TIMEOUT_SECONDS",
    "AppDataError",
    "AppDataResult",
    "clear_app_data_cache",
    "fetch_app_source",
    "find_read_endpoint",
    "service_public_id",
    "validate_params",
]


# --- bounds -----------------------------------------------------------------
#
# All per worker, all deliberately small. A dashboard is a display surface: a
# endpoint that cannot answer in five seconds inside a megabyte is not going to
# render usefully, and letting it try costs everyone sharing the process.

#: Wall-clock budget for one upstream call. Connect and read are capped
#: separately so a service that accepts a connection and then stalls still
#: returns inside the budget.
REQUEST_TIMEOUT_SECONDS = 5.0
#: Response ceiling. Read as a bounded stream, so an oversized body is abandoned
#: rather than buffered.
MAX_RESPONSE_BYTES = 1024 * 1024
#: The encoded ``params`` object a request may carry.
MAX_PARAMS_BYTES = 2048
#: How many calls to one app this worker will hold open at once. Refused rather
#: than queued: waiting behind a stalled app is the same outage with a longer
#: fuse.
MAX_INFLIGHT_PER_APP = 8
#: The longest a response is reused, whatever the manifest asks for. The manifest
#: value is already clamped at publish time; this is the deployment's own ceiling
#: so a listing cannot decide how stale a dashboard may be.
MAX_CACHE_TTL_SECONDS = 300
#: How many responses one worker keeps. Entries are small (rows for one widget)
#: and expire on their own; this only bounds a pathological spread of parameter
#: combinations.
MAX_CACHE_ENTRIES = 2048


class AppDataError(Exception):
    """A refusal with the message code and status the endpoint should answer."""

    def __init__(self, code: str, status_code: int, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class AppDataResult:
    """One endpoint's answer, and when it was actually obtained upstream."""

    rows: list[Any]
    fetched_at: datetime
    #: True when this body came from the response cache rather than the app.
    cached: bool = False


# --- reading the pinned definition ------------------------------------------


def service_public_id(definition: Mapping[str, Any] | None) -> Optional[str]:
    """Which app service backs this install, per its pinned definition."""
    body = definition or {}
    if body.get("app_kind") != "service":
        return None
    service = body.get("service")
    if not isinstance(service, dict):
        return None
    public_id = service.get("public_id")
    return public_id if isinstance(public_id, str) and public_id else None


def _endpoints(definition: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    declared = (definition or {}).get("endpoints")
    if not isinstance(declared, list):
        return []
    return [entry for entry in declared if isinstance(entry, dict)]


def find_read_endpoint(
    definition: Mapping[str, Any] | None, endpoint_id: str
) -> Optional[dict[str, Any]]:
    """One readable endpoint from the *pinned* definition, or None.

    Pinned rather than current on purpose: what an install offers is the version
    its guild chose, so publishing a new one never silently widens what an
    existing install will answer.

    Readable rather than declared, because this is the fetch path. A write and
    an emission are both real endpoints and neither is reachable from here — a
    dashboard rendering a tile must not be a way to make an app act.
    """
    for endpoint in _endpoints(definition):
        if endpoint.get("id") == endpoint_id and endpoint.get("direction") == "read":
            return endpoint
    return None


# --- parameters -------------------------------------------------------------


def _coerce_param(field_spec: Mapping[str, Any], value: Any) -> str:
    """One parameter, checked against its declared type and rendered for the
    wire. The types are the manifest's closed enum minus ``secret`` — a
    credential is supplied once and held in custody, never restated per call."""
    field_type = field_spec.get("type")

    if field_type == "bool":
        if not isinstance(value, bool):
            raise AppDataError(AppDataMessages.INVALID_PARAMS, 400)
        return "true" if value else "false"

    if field_type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise AppDataError(AppDataMessages.INVALID_PARAMS, 400)
        return str(value)

    if not isinstance(value, str):
        raise AppDataError(AppDataMessages.INVALID_PARAMS, 400)
    text = value.strip()
    if not text or len(text) > app_config_service.MAX_CONFIG_VALUE_LENGTH:
        raise AppDataError(AppDataMessages.INVALID_PARAMS, 400)

    if field_type == "select":
        options = field_spec.get("options")
        if not isinstance(options, list) or text not in options:
            raise AppDataError(AppDataMessages.INVALID_PARAMS, 400)
        return text

    if field_type == "url":
        if " " in text or not (
            text.startswith("https://") or text.startswith("http://")
        ):
            raise AppDataError(AppDataMessages.INVALID_PARAMS, 400)
        return text

    if field_type != "string":
        # A type the manifest validator would not have stored. Refused rather
        # than passed through as an unchecked string.
        raise AppDataError(AppDataMessages.INVALID_PARAMS, 400)
    return text


def validate_params(
    endpoint: Mapping[str, Any], raw: str | None
) -> tuple[dict[str, str], str]:
    """Check a request's ``params`` against the endpoint's ``params_schema``.

    Returns the values to send upstream and their canonical form for the cache
    key. A parameter the endpoint does not declare is refused rather than
    forwarded: the schema is the whole of what a widget may vary, and anything
    else would be a caller shaping the app's request directly.
    """
    if raw is None or not raw.strip():
        supplied: dict[str, Any] = {}
    else:
        if len(raw.encode("utf-8")) > MAX_PARAMS_BYTES:
            raise AppDataError(AppDataMessages.INVALID_PARAMS, 400)
        try:
            supplied = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AppDataError(AppDataMessages.INVALID_PARAMS, 400) from exc
        if not isinstance(supplied, dict):
            raise AppDataError(AppDataMessages.INVALID_PARAMS, 400)

    declared_raw = endpoint.get("params")
    declared = {
        entry["key"]: entry
        for entry in (declared_raw if isinstance(declared_raw, list) else [])
        if isinstance(entry, dict) and isinstance(entry.get("key"), str)
    }

    values: dict[str, str] = {}
    for key, value in supplied.items():
        field_spec = declared.get(key)
        if field_spec is None:
            raise AppDataError(AppDataMessages.INVALID_PARAMS, 400)
        values[key] = _coerce_param(field_spec, value)

    for key, field_spec in declared.items():
        if field_spec.get("required") is True and key not in values:
            raise AppDataError(AppDataMessages.INVALID_PARAMS, 400)

    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return values, canonical


# --- which credentials this endpoint runs on ----------------------------------


def _required_connection_ids(endpoint: Mapping[str, Any]) -> tuple[list[str], bool]:
    """The connections a endpoint names, and whether all of them are needed.

    ``requires`` is one level with one operator (§7.4). Absent means the endpoint
    needs no credential at all.
    """
    requires = endpoint.get("requires")
    if not isinstance(requires, dict):
        return [], True
    for key, needs_all in (("all_of", True), ("any_of", False)):
        terms = requires.get(key)
        if isinstance(terms, list):
            return [term for term in terms if isinstance(term, str)], needs_all
    return [], True


async def _resolve_connections(
    session: AsyncSession,
    *,
    app: GuildApp,
    endpoint: Mapping[str, Any],
    user_id: int,
) -> dict[str, str]:
    """Decide whether this endpoint can run, and collect the handles it runs with.

    Satisfaction is presence alone — which fields hold a value. This build never
    inspects a credential, calls a vendor, or learns a scope; whether a stored
    credential carries the permissions it needs is the app's to report.

    A guild-scoped connection is the same answer for everyone; a per-member one
    is answered for the caller, so a colleague who has connected sees data while
    someone who has not is told to connect rather than being served the other
    person's view.
    """
    required, needs_all = _required_connection_ids(endpoint)
    if not required:
        return {}

    config = app.config or {}
    secrets = app.config_secrets or {}
    refs: dict[str, str] = {}
    satisfied: list[str] = []
    #: The first reason a candidate failed, reported when nothing satisfies.
    refusal: AppDataError | None = None

    for connection_id in required:
        connection = app_config_service.connection_by_id(app.definition, connection_id)
        if connection is None:
            # The pinned definition names a connection it does not declare —
            # nothing can satisfy it, so the endpoint cannot run.
            refusal = refusal or AppDataError(AppDataMessages.NEEDS_CONFIGURATION, 409)
            continue

        if connection.get("scope") == "interactive":
            row = await _member_connection(
                session, app_id=app.id, connection_id=connection_id, user_id=user_id
            )
            if row is not None and row.blocked_at is not None:
                refusal = refusal or AppDataError(
                    GuildAppMessages.CONNECTION_BLOCKED, 403
                )
                continue
            if row is None or not app_config_service.is_satisfied(
                connection, row.config, row.config_secrets
            ):
                refusal = refusal or AppDataError(
                    AppDataMessages.CONNECTION_REQUIRED, 409
                )
                continue
            refs[connection_id] = row.connection_ref
            satisfied.append(connection_id)
            continue

        if not app_config_service.is_satisfied(
            connection,
            config.get(connection_id) or {},
            secrets.get(connection_id) or {},
        ):
            refusal = refusal or AppDataError(AppDataMessages.NEEDS_CONFIGURATION, 409)
            continue
        satisfied.append(connection_id)

    if needs_all and len(satisfied) != len(required):
        raise refusal or AppDataError(AppDataMessages.NEEDS_CONFIGURATION, 409)
    if not needs_all and not satisfied:
        raise refusal or AppDataError(AppDataMessages.NEEDS_CONFIGURATION, 409)
    # For ``any_of`` the handles of every satisfied candidate travel, and the app
    # picks the least-privileged one it recognizes. They are part of the cache
    # key either way, so an answer is only ever replayed to a caller holding the
    # same set.
    return refs


async def _member_connection(
    session: AsyncSession, *, app_id: int, connection_id: str, user_id: int
) -> Optional[GuildAppUserConnection]:
    return (
        await session.exec(
            select(GuildAppUserConnection).where(
                GuildAppUserConnection.app_id == app_id,
                GuildAppUserConnection.connection_id == connection_id,
                GuildAppUserConnection.user_id == user_id,
            )
        )
    ).first()


# --- the registration -------------------------------------------------------


async def _load_registration(public_id: str) -> AppServiceRegistration:
    """Where this app lives and whether the operator still allows it.

    Read on the system engine: a registration is deployment configuration in
    ``public`` with no request-path grant, so it is never reachable from the
    guild session serving the request. Read per call rather than cached, so the
    operator's kill switch takes effect on the next request in every worker.
    """
    async with db_session.AdminSessionLocal() as admin:
        row = (
            await admin.exec(
                select(AppServiceRegistration).where(
                    AppServiceRegistration.public_id == public_id
                )
            )
        ).first()
    if row is None:
        raise AppDataError(AppDataMessages.SERVICE_NOT_REGISTERED, 404)
    if not is_live(row):
        raise AppDataError(AppDataMessages.SERVICE_DISABLED, 409)
    return row


# --- the response cache -----------------------------------------------------


@dataclass
class _CacheEntry:
    result: AppDataResult
    expires_at: float


#: Keyed by the tuple built in ``_cache_key``, which contains every credential
#: the body depended on. Per worker, and per process — a body is never shared
#: across a boundary the key does not already name.
_cache: dict[str, _CacheEntry] = {}
#: One in-flight upstream call per key, so concurrent viewers of the same
#: dashboard collapse into a single request instead of a thundering herd.
_pending: dict[str, "asyncio.Future[AppDataResult]"] = {}
#: Upstream calls currently open per app, for the per-worker cap.
_inflight: dict[str, int] = {}


def clear_app_data_cache(
    *, guild_id: int | None = None, app_id: int | None = None
) -> int:
    """Drop cached bodies, optionally narrowed to one guild or one install.

    A kill must not be outlived by a cached body: uninstalling, disabling, or
    revoking a credential all end with entries that were produced under the
    authority just withdrawn. The kill switches are re-read on every request, so
    this is defence in depth rather than the only thing standing between a
    revocation and a stale row.
    """
    prefix = ""
    if guild_id is not None:
        prefix = f"{guild_id}:" if app_id is None else f"{guild_id}:{app_id}:"
    dropped = [key for key in _cache if not prefix or key.startswith(prefix)]
    for key in dropped:
        _cache.pop(key, None)
    return len(dropped)


def _cache_key(
    *,
    app: GuildApp,
    endpoint_id: str,
    canonical_params: str,
    refs: Mapping[str, str],
) -> str:
    """Every credential the response depended on, in one string.

    Guild and install lead so an entry is scoped to the same boundary the
    request was, and a prefix drop can retire one install's answers. The
    fingerprint covers the stored configuration as a whole rather than only the
    connections this endpoint named: rotating a credential is rare next to reading
    a widget, and narrowing it would trade a cheap hash for the chance of
    serving a body a withdrawn credential produced.
    """
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "version": app.listing_version,
                "config": app.config or {},
                "secrets": app.config_secrets or {},
                "refs": dict(sorted(refs.items())),
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return f"{app.guild_id}:{app.id}:{endpoint_id}:{canonical_params}:{fingerprint}"


def _cache_get(key: str) -> Optional[AppDataResult]:
    entry = _cache.get(key)
    if entry is None:
        return None
    if entry.expires_at <= time.monotonic():
        _cache.pop(key, None)
        return None
    return AppDataResult(
        rows=entry.result.rows, fetched_at=entry.result.fetched_at, cached=True
    )


def _cache_put(key: str, result: AppDataResult, ttl: int) -> None:
    if ttl <= 0:
        return
    if len(_cache) >= MAX_CACHE_ENTRIES:
        now = time.monotonic()
        for stale in [k for k, v in _cache.items() if v.expires_at <= now]:
            _cache.pop(stale, None)
        while len(_cache) >= MAX_CACHE_ENTRIES:
            # Dicts preserve insertion order, so the oldest write goes first.
            _cache.pop(next(iter(_cache)), None)
    _cache[key] = _CacheEntry(result=result, expires_at=time.monotonic() + ttl)


def _effective_ttl(endpoint: Mapping[str, Any]) -> int:
    declared = endpoint.get("cache_ttl_seconds")
    if isinstance(declared, bool) or not isinstance(declared, int):
        return 0
    return max(0, min(declared, MAX_CACHE_TTL_SECONDS))


# --- the upstream call ------------------------------------------------------


#: Every app answers every endpoint here. Fixed by the protocol rather than
#: chosen per app, so a caller that knows an id needs nothing else.
ENDPOINTS_PATH = "/v1/endpoints"


def _endpoints_url(registration: AppServiceRegistration) -> str:
    """Where this app answers: the operator's base URL joined to the one path
    every app serves. A manifest names an endpoint; only a registration says
    where the app is."""
    return f"{registration.base_url.rstrip('/')}{ENDPOINTS_PATH}"


async def _read_rows(
    request: httpx.Request, *, transport: httpx.AsyncBaseTransport | None
) -> list[Any]:
    """Send one bounded request and return the rows it answered with.

    Read as a stream against a byte ceiling, parsed as JSON only, and refused
    unless the body is an object carrying a ``rows`` list. Everything else is
    reported as the app being unavailable — a dashboard tile says "this app is
    not answering", which is true whether the service is down or talking a shape
    this build does not accept.
    """
    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=REQUEST_TIMEOUT_SECONDS)
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, transport=transport
        ) as client:
            response = await client.send(request, stream=True)
            try:
                if response.status_code >= 400:
                    raise AppDataError(
                        AppDataMessages.SERVICE_UNAVAILABLE,
                        502,
                        f"app answered {response.status_code}",
                    )
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise AppDataError(
                            AppDataMessages.RESPONSE_TOO_LARGE,
                            502,
                            "response exceeded the ceiling",
                        )
                    chunks.append(chunk)
            finally:
                await response.aclose()
    except httpx.HTTPError as exc:
        raise AppDataError(
            AppDataMessages.SERVICE_UNAVAILABLE, 502, f"app could not be read: {exc}"
        ) from exc

    try:
        body = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppDataError(
            AppDataMessages.SERVICE_UNAVAILABLE, 502, "app did not answer with JSON"
        ) from exc

    # The app answers with what it did — the endpoint it ran, whose credential
    # ran it, and the result — so the rows are one level in. Reported as the app
    # being unavailable rather than as a bad request: from a dashboard's side
    # "this app is not answering" is true whether the service is down or talking
    # a shape this build does not accept.
    result = body.get("result") if isinstance(body, dict) else None
    rows = result.get("rows") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise AppDataError(
            AppDataMessages.SERVICE_UNAVAILABLE, 502, "app answered without rows"
        )
    return rows


async def _call_app(
    *,
    registration: AppServiceRegistration,
    app: GuildApp,
    endpoint: Mapping[str, Any],
    endpoint_id: str,
    params: Mapping[str, str],
    refs: Mapping[str, str],
    transport: httpx.AsyncBaseTransport | None,
) -> AppDataResult:
    """One upstream call, under this worker's in-flight cap for the app."""
    if not app_platform_signing_enabled():
        raise AppDataError(AppServiceMessages.SIGNING_NOT_CONFIGURED, 503)

    public_id = registration.public_id
    if _inflight.get(public_id, 0) >= MAX_INFLIGHT_PER_APP:
        logger.info(
            "app data: %s is at this worker's in-flight ceiling (%s)",
            public_id,
            MAX_INFLIGHT_PER_APP,
        )
        raise AppDataError(AppDataMessages.BUSY, 503)
    _inflight[public_id] = _inflight.get(public_id, 0) + 1
    try:
        try:
            token, _ = mint_context_token(
                public_id=public_id,
                guild_id=app.guild_id,
                app_install_id=app.id,
                scope="endpoint",
                endpoint_id=endpoint_id,
                connection_refs=refs,
            )
        except AppPlatformSigningNotConfiguredError as exc:
            raise AppDataError(AppServiceMessages.SIGNING_NOT_CONFIGURED, 503) from exc

        # POST rather than GET, and a body rather than a query string: one
        # path serves every endpoint, so which one is being called is part of
        # what is sent rather than part of where it is sent.
        try:
            request = await build_validated_request(
                "POST",
                _endpoints_url(registration),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                content=json.dumps(
                    {
                        "endpoint": endpoint_id,
                        "guild_id": app.guild_id,
                        "params": dict(params),
                    }
                ).encode("utf-8"),
                # An app service is an operator-configured destination and is
                # typically a container on the deployment's own network. Plain
                # http stays confined to those addresses by the target policy.
                allow_private=True,
            )
        except (WebhookTargetUrlError, WebhookTargetUrlPrivateError) as exc:
            raise AppDataError(
                AppDataMessages.SERVICE_UNAVAILABLE, 502, f"target refused: {exc}"
            ) from exc

        rows = await _read_rows(request, transport=transport)
        return AppDataResult(rows=rows, fetched_at=datetime.now(timezone.utc))
    finally:
        remaining = _inflight.get(public_id, 1) - 1
        if remaining > 0:
            _inflight[public_id] = remaining
        else:
            _inflight.pop(public_id, None)


# --- the whole path ---------------------------------------------------------


async def fetch_app_source(
    session: AsyncSession,
    *,
    app: GuildApp,
    endpoint_id: str,
    raw_params: str | None,
    user_id: int,
    is_guild_admin: bool,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AppDataResult:
    """Resolve one endpoint for one caller.

    The install has already been loaded under the caller's own guild session, so
    the guild boundary and a guild admin's wider reach are settled before this
    runs. What is decided here is the app's own vocabulary: the endpoint exists,
    the caller is allowed to see it, both kill switches are open, the parameters
    are ones the endpoint declared, and the credentials it named are present.
    """
    endpoint = find_read_endpoint(app.definition, endpoint_id)
    public_id = service_public_id(app.definition)
    if endpoint is None or public_id is None:
        raise AppDataError(AppDataMessages.SOURCE_NOT_FOUND, 404)

    # Measured against the same ladder a manifest declares on, so the two
    # cannot come to mean different things.
    if not clears_visibility(endpoint.get("visibility"), is_guild_admin=is_guild_admin):
        raise AppDataError(AppDataMessages.ADMIN_ONLY, 403)
    if not app.enabled:
        raise AppDataError(AppDataMessages.APP_DISABLED, 409)

    registration = await _load_registration(public_id)
    params, canonical = validate_params(endpoint, raw_params)
    refs = await _resolve_connections(
        session, app=app, endpoint=endpoint, user_id=user_id
    )

    key = _cache_key(
        app=app, endpoint_id=endpoint_id, canonical_params=canonical, refs=refs
    )
    cached = _cache_get(key)
    if cached is not None:
        return cached

    pending = _pending.get(key)
    if pending is not None:
        # Someone is already asking this exact question with these exact
        # credentials. Wait for their answer rather than making a second call.
        return await asyncio.shield(pending)

    loop = asyncio.get_running_loop()
    future: "asyncio.Future[AppDataResult]" = loop.create_future()
    _pending[key] = future
    try:
        result = await _call_app(
            registration=registration,
            app=app,
            endpoint=endpoint,
            endpoint_id=endpoint_id,
            params=params,
            refs=refs,
            transport=transport,
        )
    except BaseException as exc:  # noqa: BLE001 - re-raised after the handoff
        if not future.done():
            future.set_exception(exc)
        # Nobody may be waiting; reading the result keeps asyncio from logging
        # the exception as never retrieved.
        future.exception()
        raise
    else:
        if not future.done():
            future.set_result(result)
        _cache_put(key, result, _effective_ttl(endpoint))
        return result
    finally:
        _pending.pop(key, None)
