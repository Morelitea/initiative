"""What the IdP said about an authentication, kept against the provider.

An OIDC id_token can describe the authentication event that produced it:
``amr`` names the methods used (RFC 8176 registers the common ones), ``acr``
the context class the IdP claims it meets, and ``auth_time`` when it happened.
The callback used to read none of them and record one marker naming the
provider, so a corporate sign-in that already carried a second factor looked
exactly like one that did not.

These are recorded **per provider**, not per session. One session can satisfy
several guilds' identity sources at once, and each guild's requirement is about
its own provider's authentication event — a step-up into one guild's IdP says
nothing about when another's last authenticated.

The values come from the provider, so this module fixes their shape and size
before they reach a session row or an access token.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# What one provider may contribute. These ride in a session row and in every
# access token minted from it, so the size is settled here rather than by the
# IdP.
MAX_AMR_VALUES = 16
MAX_AMR_VALUE_LENGTH = 64
MAX_ACR_LENGTH = 256

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
        return record


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


def session_amr(provider_slug: str, assurance: ProviderAssurance) -> list[str]:
    """The session-level ``amr`` one provider login contributes: our own marker
    naming the provider, plus the methods the IdP named.

    The marker is what a guild policy keyed to *this* provider matches; the
    IdP's own values are what an assurance-only policy reads.
    """
    return sorted({f"oidc:{provider_slug}", *assurance.amr})


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
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value > 0 else None
    if isinstance(value, str) and value.isdigit():
        seconds = int(value)
        return seconds if seconds > 0 else None
    return None


def _read_amr(value: Any) -> tuple[str, ...]:
    # OIDC Core §2: a JSON array of case-sensitive strings. RFC 8176 registers
    # the common names, but a provider may use its own, so the values are taken
    # as given rather than checked against a list.
    if not isinstance(value, list):
        return ()
    kept: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            continue
        cleaned = entry.strip()
        if not cleaned or len(cleaned) > MAX_AMR_VALUE_LENGTH:
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
