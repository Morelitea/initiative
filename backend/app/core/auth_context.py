"""Request-scoped satisfied-auth-provider context.

The credential validators (``get_current_user``, ``get_upload_user``, the
WebSocket ``authenticate_ws_token``) record here which login providers the
current session credential has satisfied — its token's ``sat`` claim. The
guild-access gate and every session-routing seam (``establish_guild_access``,
``get_guild_session``, ``gather_across_guilds``) read it to feed the guild
auth-policy check and the ``app.satisfied_providers`` GUC behind
``public.guild_auth_satisfied()``, without the value being threaded through
every helper between the validator and the sink (mirroring ``role_context``).

Alongside it, the communities whose own single sign-on the session completed
(read back from its ``amr`` markers), which the same gate gives to
``app.sso_guilds``.

The value is either the frozenset of provider ids the session proved, or the
``SYSTEM_SATISFIED`` sentinel string (see ``app.db.session``) that
user-attributed system work sets explicitly. The default is the empty set —
credentials that carry no ``sat`` (legacy tokens, API keys, device tokens,
delegation JWTs) fail closed against policy-gated guilds.
"""

from __future__ import annotations

import contextvars

_satisfied_providers: contextvars.ContextVar[frozenset[int] | str] = (
    contextvars.ContextVar("auth_satisfied_providers", default=frozenset())
)


def set_satisfied_providers(value: frozenset[int] | str | None) -> None:
    """Record the current credential's satisfied-provider set (or the system
    sentinel). ``None`` clears to the fail-closed empty set."""
    _satisfied_providers.set(frozenset() if value is None else value)


def satisfied_providers() -> frozenset[int] | str:
    """The satisfied-provider set recorded for this request/task."""
    return _satisfied_providers.get()


def satisfied_provider_ids() -> frozenset[int]:
    """The recorded set as provider ids only — the system sentinel (which no
    live-session path records) reads as the empty, fail-closed set."""
    value = _satisfied_providers.get()
    return value if isinstance(value, frozenset) else frozenset()


_sso_guilds: contextvars.ContextVar[frozenset[int]] = contextvars.ContextVar(
    "auth_sso_guilds", default=frozenset()
)


def set_sso_guilds(value: frozenset[int] | None) -> None:
    """Record the communities whose own single sign-on this session completed."""
    _sso_guilds.set(frozenset() if value is None else value)


def sso_guilds() -> frozenset[int]:
    """Those communities, for this request/task.

    Empty for every credential that records nothing about how its owner signed
    in — device tokens, API keys, delegation JWTs — which is the fail-closed
    answer against a community asking for its own sign-in.
    """
    return _sso_guilds.get()


#: The ``user_tokens`` row that authenticated this request, when the credential
#: was a device token. It names one installed client, which is the only stable
#: handle the server has on "this phone" — a push token rotates and a login
#: expires, so anything that has to recognise the same installation twice
#: (linking its push registration to its message key store) keys on this.
#: ``None`` for every other credential, including the web session: a browser
#: has no device token and minting one to tidy the join would put a long-lived
#: credential where it does not belong.
_device_token_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "auth_device_token_id", default=None
)


def set_device_token_id(value: int | None) -> None:
    """Record the device token that authenticated this request (or clear it)."""
    _device_token_id.set(value)


def device_token_id() -> int | None:
    """The device token recorded for this request, if it was authenticated by
    one."""
    return _device_token_id.get()
