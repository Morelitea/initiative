"""Request-scoped satisfied-auth-provider context.

The credential validators (``get_current_user``, ``get_upload_user``, the
WebSocket ``authenticate_ws_token``) record here which login providers the
current session credential has satisfied — its token's ``sat`` claim. The
guild-access gate and every session-routing seam (``establish_guild_access``,
``get_guild_session``, ``gather_across_guilds``) read it to feed the guild
auth-policy check and the ``app.satisfied_providers`` GUC behind
``public.guild_auth_satisfied()``, without the value being threaded through
every helper between the validator and the sink.

Alongside it, what each of those providers asserted for the claims some
community narrows it by — its token's ``satd`` claim — which the same gate
gives to ``app.satisfied_claims``. The session carries the fact; the
connection carries the rule, and the two meet in the gate.

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


_satisfied_claims: contextvars.ContextVar[dict[str, dict[str, list[str]]]] = (
    contextvars.ContextVar("auth_satisfied_claims", default={})
)


def set_satisfied_claims(value: dict[str, dict[str, list[str]]] | None) -> None:
    """Record what each satisfied provider asserted, keyed by provider id."""
    _satisfied_claims.set(value or {})


def satisfied_claims() -> dict[str, dict[str, list[str]]]:
    """Those assertions, for this request/task.

    Empty for every credential that records nothing about how its owner signed
    in — device tokens, API keys, delegation JWTs — which is the fail-closed
    answer against a community that narrows the way in.
    """
    return _satisfied_claims.get()


def claims_from_provider_auth(
    record: dict | None,
) -> dict[str, dict[str, list[str]]]:
    """The narrowing assertions out of a ``satd``/``provider_auth`` record.

    Shaped for the gate: ``{"12": {"hd": ["acme.com"]}}``. Anything that is
    not that shape is dropped rather than coerced.
    """
    found: dict[str, dict[str, list[str]]] = {}
    for provider_id, entry in (record or {}).items():
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


#: Which of the markers a community can ask about this request's credential
#: recorded. Read from the session's own ``amr`` and narrowed to
#: ``POLICY_AMR_MARKERS`` by ``policy_markers`` — ``mfa`` where a code was
#: presented, ``hwk``/``swk`` where a key answered — then handed to the
#: database as ``app.session_amr`` so a community's rule is answered there as
#: well as here.
#:
#: One set rather than a flag per method: a rule asking for a passkey and a
#: rule asking for a factor are two readings of the same sentence the sign-in
#: wrote, and a boolean each meant every seam between the validator and the
#: gate grew a parameter every time a method was added.
#:
#: Empty for every credential that is not a session — an API key, a delegation
#: JWT — which is the fail-closed answer to any community that asks.
_session_amr: contextvars.ContextVar[frozenset[str]] = contextvars.ContextVar(
    "auth_session_amr", default=frozenset()
)


def set_session_amr(value: frozenset[str] | None) -> None:
    """Record the markers this credential proved. ``None`` clears to the
    fail-closed empty set."""
    _session_amr.set(frozenset() if value is None else frozenset(value))


def session_amr() -> frozenset[str]:
    """Those markers, for this request/task."""
    return _session_amr.get()


#: Whether the account this request is made by answers the deployment's own
#: second-factor rule: a second factor it holds, or one this session
#: presented. Its own reading rather than :func:`session_amr`'s, because the
#: two questions are different — a community asks what *this session* proved,
#: and the deployment asks what the *account* has — and because a credential
#: that cannot present one (the app's device token, a personal API key) still
#: answers the deployment by the account holding a factor.
#:
#: Resolved once per request by the gate in ``app.api.deps`` and handed to the
#: database, which decides the rule itself from the settings row.
_platform_factor: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "auth_platform_factor", default=False
)


def set_platform_factor(value: bool) -> None:
    _platform_factor.set(bool(value))


def platform_factor() -> bool:
    return _platform_factor.get()


#: Whether a personal API key is what authenticated this request. Recorded by
#: the two validators that accept one, and read where a community's refusal of
#: them is applied: the guild-access gate and the cross-guild aggregates.
#: ``False`` for every other credential, which is the answer that reaches the
#: guild.
_api_key_credential: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "auth_api_key_credential", default=False
)


def set_api_key_credential(value: bool) -> None:
    _api_key_credential.set(bool(value))


def api_key_credential() -> bool:
    return _api_key_credential.get()


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
