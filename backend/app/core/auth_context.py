"""What the credential behind a request recorded about its sign-in.

The credential validator (``app.services.auth.credentials``, which
``get_current_user``, ``get_upload_user`` and the WebSocket
``authenticate_ws_token`` all go through) records here, as one
:class:`AuthContext`, which login providers the current session credential has
satisfied — its token's ``sat`` claim — and what each of them asserted for the
claims some community narrows it by (``satd``), the markers its ``amr``
carries, which session it was, and whether it was a personal API key and the
guild that key is limited to. The deployment's second-factor gate in
``app.api.deps`` adds its own answer beside them. The guild-access gate and
every session-routing seam (``establish_guild_access``, ``get_guild_session``,
``gather_across_guilds``) read it to feed the guild auth-policy check and the
GUCs behind ``public.guild_auth_satisfied()``, without the value being threaded
through every helper between the validator and the sink. The session carries
the fact; the connection carries the rule, and the two meet in the gate.

Work a job does on somebody's behalf is routed with ``on_behalf`` instead
(``app.api.deps.establish_guild_access``). Every default is the closed answer:
credentials that carry no ``sat`` (legacy tokens, API keys) fail closed against
policy-gated guilds.
"""

from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from app.core.login_methods import SecondFactorRequirement


@dataclass(frozen=True)
class SessionCredential:
    """The session JWT that authenticated this request, by the two values
    that say whether it still stands: the ``auth_sessions`` row its ``sid``
    names, and the ``users.token_version`` it was minted at.

    Recorded by the credential validator for every session JWT. A stream
    registered on a socket reads it, so it can ask again later, after the
    request that opened it is long gone. ``None`` for every other credential.
    """

    session_id: uuid.UUID
    token_version: int


@dataclass(frozen=True)
class AuthContext:
    """What the credential behind this request/task recorded about itself.

    Replaced whole rather than edited: :func:`record` sets a copy with the
    named fields changed, and :func:`reset` sets the empty one, so starting
    over cannot leave a field behind.
    """

    #: The login providers the session satisfied — its token's ``sat`` claim.
    satisfied_providers: frozenset[int] = frozenset()
    #: What each of those providers asserted for the claims some community
    #: narrows it by — its token's ``satd`` claim — keyed by provider id, as
    #: :func:`claims_from_provider_auth` shapes it. Empty for every credential
    #: that records nothing about how its owner signed in.
    satisfied_claims: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    #: Which of the markers a community can ask about the credential recorded.
    #: Read from the session's own ``amr`` and narrowed to
    #: ``POLICY_AMR_MARKERS`` by ``policy_markers`` — ``mfa`` where a code was
    #: presented, ``hwk``/``swk`` where a key answered — then handed to the
    #: database as ``app.session_amr`` so a community's rule is answered there
    #: as well as here. One set rather than a flag per method: a rule asking
    #: for a passkey and a rule asking for a factor are two readings of the
    #: same sentence the sign-in wrote. Empty for every credential that is not
    #: a session.
    session_amr: frozenset[str] = frozenset()
    #: Whether the account answers the deployment's own second-factor rule: a
    #: second factor it holds, or one this session presented. Its own reading
    #: rather than :attr:`session_amr`'s, because a community asks what *this
    #: session* proved and the deployment asks what the *account* has. Resolved
    #: once per request by the gate in ``app.api.deps`` and handed to the
    #: database, which decides the rule itself from the settings row.
    platform_factor: bool = False
    #: What the deployment asks of an account, as the credential validator read
    #: it beside the account itself. ``None`` where nothing read it — every
    #: credential but the session — and the question is then read when it is
    #: asked.
    asked_of_account: SecondFactorRequirement | None = None
    #: Whether a personal API key is what authenticated this request. Read where
    #: a community's refusal of them is applied: the guild-access gate and the
    #: cross-guild aggregates.
    api_key_credential: bool = False
    #: The one guild a personal API key is limited to, when it is limited to
    #: one. The guild-access gate refuses every other guild, and the
    #: cross-guild aggregates visit only this one.
    api_key_guild_id: int | None = None
    #: The session JWT that authenticated this request, for every session JWT
    #: that names its row.
    session_credential: SessionCredential | None = None


_EMPTY = AuthContext()

_current: contextvars.ContextVar[AuthContext] = contextvars.ContextVar(
    "auth_context", default=_EMPTY
)


def current() -> AuthContext:
    """What this request/task's credential recorded."""
    return _current.get()


def record(**changes: Any) -> None:
    """Record ``changes`` beside what is already recorded."""
    _current.set(replace(_current.get(), **changes))


def reset(context: AuthContext = _EMPTY) -> None:
    """Forget everything recorded, and record ``context`` in its place."""
    _current.set(context)


def claims_from_provider_auth(
    provider_auth: dict | None,
) -> dict[str, dict[str, list[str]]]:
    """The narrowing assertions out of a ``satd``/``provider_auth`` record.

    Shaped for the gate: ``{"12": {"hd": ["acme.com"]}}``. Anything that is
    not that shape is dropped rather than coerced.
    """
    found: dict[str, dict[str, list[str]]] = {}
    for provider_id, entry in (provider_auth or {}).items():
        # A decoded token hands these over as models; the session row's own
        # column hands them over as plain JSON.
        claims = (
            entry.get("claims")
            if isinstance(entry, dict)
            else getattr(entry, "claims", None)
        )
        if not isinstance(claims, dict):
            continue
        kept = {
            str(name): [str(v) for v in values]
            for name, values in claims.items()
            if isinstance(values, (list, tuple)) and values
        }
        if kept:
            found[str(provider_id)] = kept
    return found
