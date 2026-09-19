"""What the IdP said about an authentication, kept against the provider.

An OIDC id_token can describe the authentication event that produced it:
``amr`` names the methods used (RFC 8176 registers the common ones), ``acr``
the context class the IdP claims it meets, and ``auth_time`` when it happened.
The callback used to read none of them and record one marker naming the
provider, so a corporate sign-in that already carried a second factor looked
exactly like one that did not.

These are recorded **per provider**, not per session. One session can satisfy
several guilds' identity sources at once, and each guild's requirement is about
its own provider's authentication event — a step-up through one provider says
nothing about when another last authenticated.

The values come from the provider, so this module fixes their shape and size
before they reach a session row or an access token.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# What one provider may contribute. These ride in a session row and in every
# access token minted from it, so the size is settled here rather than by the
# IdP.
MAX_AMR_VALUES = 16
MAX_AMR_VALUE_LENGTH = 64
MAX_ACR_LENGTH = 256

#: Names the provider a session came in through.
PROVIDER_AMR_PREFIX = "oidc:"

#: What a session records when the account's own second factor was presented.
#: RFC 8176 registers it for exactly this: more than one factor was used. A
#: TOTP code writes ``otp`` beside it; a recovery code does not, so a rule can
#: tell a live authenticator from the set kept for losing it.
SECOND_FACTOR_AMR = "mfa"

#: What a session records for the kind of passkey that answered. RFC 8176
#: registers both: ``hwk`` for a key held by hardware — a security key, a TPM,
#: a Secure Enclave — and ``swk`` for one a password manager syncs between the
#: person's devices. Which it is comes off the credential's own backed-up flag.
PASSKEY_AMR_VALUES: tuple[str, ...] = ("hwk", "swk")

#: Marks a session as having completed one community's own single sign-on.
#: Written when the provider is that community's rather than the deployment's,
#: so a rule reading "any of ours" can be answered from the session alone.
GUILD_AMR_PREFIX = "guild:"

#: The prefixes this application writes into a session's ``amr`` itself. They
#: are its own account of a sign-in, so a value arriving under one of them from
#: an identity provider is dropped rather than kept: a provider's ``amr`` is the
#: provider's own vocabulary, and these markers are not part of it.
RESERVED_AMR_PREFIXES = (PROVIDER_AMR_PREFIX, GUILD_AMR_PREFIX)

# The far end of what could be a time: 9999-12-31T23:59:59Z in epoch seconds.
# A value past it is not a timestamp, whatever else it is.
MAX_AUTH_TIME = 253_402_300_799
_MAX_AUTH_TIME_DIGITS = len(str(MAX_AUTH_TIME))

# How many providers one session keeps an account for. A session gains an entry
# per identity source it authenticates against — none for a consumer, a handful
# for someone in several enterprise guilds.
MAX_TRACKED_PROVIDERS = 32


@dataclass(frozen=True)
class ProviderAssurance:
    """One provider's account of one authentication event."""

    auth_time: int | None = None
    amr: tuple[str, ...] = ()
    acr: str | None = None
    #: What this provider asserted for the claims some community narrows it
    #: by — ``{"hd": ("acme.com",)}``. A fact about the authentication, kept
    #: beside the others, so the rule about which values count can be read
    #: fresh at the moment somebody reaches a community.
    claims: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def as_record(self) -> dict[str, Any]:
        """The stored form: what lands in ``auth_sessions.provider_auth`` and
        in the access token's ``satd`` claim. Absent claims are absent keys —
        an IdP that says nothing records nothing."""
        record: dict[str, Any] = {}
        if self.auth_time is not None:
            record["auth_time"] = self.auth_time
        if self.amr:
            record["amr"] = list(self.amr)
        if self.acr is not None:
            record["acr"] = self.acr
        if self.claims:
            record["claims"] = {name: list(values) for name, values in self.claims}
        return record


#: How many values one claim contributes. A group list can be long, and this
#: rides in the access token; a community narrows on a handful.
MAX_CLAIM_VALUES = 24


def read_narrowing(
    claims: Mapping[str, Any],
    userinfo: Mapping[str, Any] | None,
    names: Iterable[str],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """What this provider asserted for each named claim.

    ``names`` are the claims some community narrows this provider by, so a
    provider nobody narrows records nothing. Values are read through the same
    dot-path extractor the group rules use, so a nested path works here too.
    """
    from app.services.oidc_sync import extract_claim_values

    found: list[tuple[str, tuple[str, ...]]] = []
    for name in sorted({str(n) for n in names if n}):
        values = extract_claim_values(userinfo or {}, claims, name)
        if values:
            found.append((name, tuple(sorted(values))[:MAX_CLAIM_VALUES]))
    return tuple(found)


def read_assurance(claims: Mapping[str, Any]) -> ProviderAssurance:
    """The assurance claims of a **verified** id_token, normalised.

    A claim in a shape OIDC Core does not describe is dropped rather than
    coerced: a malformed ``amr`` is no ``amr``, not a guess at one.
    """
    return ProviderAssurance(
        auth_time=_read_auth_time(claims.get("auth_time")),
        amr=_read_amr(claims.get("amr")),
        acr=_read_acr(claims.get("acr")),
    )


def passkey_amr(*, backed_up: bool) -> list[str]:
    """The ``amr`` a passkey sign-in contributes.

    Two values. Which kind of key answered, and :data:`SECOND_FACTOR_AMR`:
    every ceremony here requires user verification, so an assertion proves both
    something the person has and something they are — which is what RFC 8176
    means by a multi-factor cryptographic authenticator.
    """
    return ["swk" if backed_up else "hwk", SECOND_FACTOR_AMR]


def carries_passkey(amr: Iterable[str]) -> bool:
    """Whether this session was opened, or stepped up, with a passkey."""
    return any(value in PASSKEY_AMR_VALUES for value in amr)


def session_amr(
    provider_slug: str,
    assurance: ProviderAssurance,
) -> list[str]:
    """The session-level ``amr`` one provider login contributes: our own marker
    naming the provider, plus the methods the IdP named.

    The provider marker is what a guild policy keyed to *this* provider
    matches; the IdP's own values are what an assurance-only policy reads. A
    policy asking for any of a community's providers is answered from the
    connections themselves, so no marker names a community.
    """
    markers = {f"{PROVIDER_AMR_PREFIX}{provider_slug}"}
    return sorted({*markers, *assurance.amr})


def record_for_provider(
    prior: Mapping[str, Any] | None,
    *,
    provider_id: int,
    assurance: ProviderAssurance,
) -> dict[str, dict[str, Any]]:
    """``prior`` with ``provider_id``'s entry replaced by ``assurance``.

    Keys are provider ids as strings, because this is a JSON object in both
    places it lives. The newest authentication replaces that provider's entry
    and leaves every other provider's account of its own event alone.

    A provider that asserts nothing gets no entry, and a stale one is removed:
    ``satisfied_providers`` already records that the provider was satisfied, so
    an empty entry adds nothing, and keeping the previous one would describe an
    authentication that did not happen this way.

    Bounded by :data:`MAX_TRACKED_PROVIDERS`. The provider just authenticated
    is always kept; beyond the bound, the least recently authenticated entries
    are dropped.
    """
    merged = {
        str(key): dict(value)
        for key, value in (prior or {}).items()
        if isinstance(value, dict)
    }
    keep = str(provider_id)
    record = assurance.as_record()
    if record:
        merged[keep] = record
    else:
        merged.pop(keep, None)
    if len(merged) <= MAX_TRACKED_PROVIDERS:
        return merged

    by_recency = sorted(
        (key for key in merged if key != keep),
        key=lambda key: merged[key].get("auth_time") or 0,
        reverse=True,
    )
    retained = {keep: merged[keep]} if keep in merged else {}
    for key in by_recency[: MAX_TRACKED_PROVIDERS - len(retained)]:
        retained[key] = merged[key]
    return retained


def _read_auth_time(value: Any) -> int | None:
    # OIDC Core §2: seconds since the epoch. bool is an int subclass in Python,
    # and some IdPs send the number as a JSON string.
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        # Length before conversion: Python refuses to convert a digit string
        # past a few thousand characters at all, and a number that long is not
        # a time either way.
        if not value.isdigit() or len(value) > _MAX_AUTH_TIME_DIGITS:
            return None
        value = int(value)
    elif isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    if not isinstance(value, int):
        return None
    return value if 0 < value <= MAX_AUTH_TIME else None


def _read_amr(value: Any) -> tuple[str, ...]:
    # OIDC Core §2: a JSON array of case-sensitive strings. RFC 8176 registers
    # the common names, but a provider may use its own, so the values are taken
    # as given rather than checked against a list — except under the prefixes
    # this application writes for itself, which are dropped (see
    # RESERVED_AMR_PREFIXES).
    if not isinstance(value, list):
        return ()
    kept: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            continue
        cleaned = entry.strip()
        if not cleaned or len(cleaned) > MAX_AMR_VALUE_LENGTH:
            continue
        if cleaned.startswith(RESERVED_AMR_PREFIXES):
            continue
        if cleaned not in kept:
            kept.append(cleaned)
        if len(kept) == MAX_AMR_VALUES:
            break
    return tuple(kept)


def _read_acr(value: Any) -> str | None:
    # OIDC Core §2: a single case-sensitive string.
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > MAX_ACR_LENGTH:
        return None
    return cleaned
