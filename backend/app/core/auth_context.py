"""Request-scoped satisfied-auth-provider context.

The credential validators (``get_current_user``, ``get_upload_user``, the
WebSocket ``authenticate_ws_token``) record here which login providers the
current session credential has satisfied — its token's ``sat`` claim. The
guild-access gate and every session-routing seam (``establish_guild_access``,
``get_guild_session``, ``gather_across_guilds``) read it to feed the guild
auth-policy check and the ``app.satisfied_providers`` GUC behind
``public.guild_auth_satisfied()``, without the value being threaded through
every helper between the validator and the sink (mirroring ``role_context``).

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
