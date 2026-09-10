"""Showing an address back without disclosing it.

An address is the one identifier in this product that is also a way to reach
somebody off it, and the one an attacker most wants out of a compromised staff
account. So no read path hands one back in full. The masked form is enough to
recognise an address you already have — matching a support ticket to a row,
telling one pending invite from another — and not enough to learn one.

Masking lives here, applied by the *shapes* (``AdminUserRead``,
``GuildInviteRead``, ``AccessGrantRead``) rather than by each endpoint, so a
new route serving one of them cannot forget. The unmasked address stays
readable only where the reader is its owner (``/users/me``) and to the code
that sends mail.
"""

from __future__ import annotations

from typing import Optional

#: What replaces the elided middle. Three asterisks regardless of how much was
#: taken out — the length of an address is part of it, so the mask is a fixed
#: width rather than one asterisk per character.
ELISION = "***"


def _mask_part(part: str) -> str:
    """First character, elision, last character — ``example`` -> ``e***e``.

    A one-character part has no distinct last character, and repeating the
    single one would claim a second that isn't there, so it gets the elision
    alone.
    """
    if len(part) == 1:
        return f"{part}{ELISION}"
    return f"{part[0]}{ELISION}{part[-1]}"


def mask_email(value: Optional[str]) -> Optional[str]:
    """``user1@example.com`` -> ``u***1@e***m``.

    Both halves are reduced the same way: first character, elision, last
    character. The domain is elided along with the local part — a bare domain
    narrows an address to one organisation, which is most of the way to
    guessing it — and everything between, dots included, goes with it.

    ``None`` and ``""`` pass through unchanged so callers don't special-case
    an address that was never set. Anything that doesn't parse as an address
    (no ``@``, or nothing before it) masks to the elision alone rather than
    being echoed back on the chance that it is one.
    """
    if not value:
        return value
    local, separator, domain = value.strip().partition("@")
    if not separator or not local or not domain:
        return ELISION
    return f"{_mask_part(local)}@{_mask_part(domain)}"
