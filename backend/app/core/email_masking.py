"""Showing an address back without disclosing it.

A guild admin types an address to bind an invite to it. Reading it back in full
is not part of that: whoever typed it already has it, and a guild's other
admins never did. The masked form still tells one pending invite from another.
"""

from __future__ import annotations

from typing import Optional


def mask_email(value: Optional[str]) -> Optional[str]:
    """``jordan@example.com`` -> ``j•••@example.com``.

    Keeps the first character of the local part and the whole domain — enough
    to recognise an address you already know, not enough to learn one.
    """
    if not value:
        return value
    local, separator, domain = value.partition("@")
    if not separator or not local:
        return "•••"
    return f"{local[0]}•••@{domain}"
