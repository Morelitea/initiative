from __future__ import annotations

from typing import Iterable

from app.core.guild_auth_options import GuildAuthOption


#: May upload banner artwork — ``guild_administration.banner_image_enabled``.
BANNER_IMAGE = "banner_image"
#: May send a help request to whoever runs this deployment —
#: ``guild_administration.support_enabled``.
HELP_REQUESTS = "help_requests"
#: May say which of the deployment's providers are its own, what their groups
#: mean, and whether members must arrive that way — ``auth_options.providers``.
GUILD_SIGN_IN = "guild_sign_in"
#: May refuse personal API keys and hold members to the session standard —
#: ``auth_options.restrictions``.
SECURITY_STANDARDS = "security_standards"

#: Capability name -> the sign-in option it grants. Every other capability is a
#: column of its own; these two share one array.
_AUTH_OPTIONS: dict[str, GuildAuthOption] = {
    GUILD_SIGN_IN: GuildAuthOption.providers,
    SECURITY_STANDARDS: GuildAuthOption.restrictions,
}

#: Every name this build understands. Used by the tests that keep the two
#: repositories' vocabularies in step; the boundary itself ignores the rest.
KNOWN_CAPABILITIES: frozenset[str] = frozenset(
    {BANNER_IMAGE, HELP_REQUESTS, *_AUTH_OPTIONS}
)


def administration_values(package: Iterable[str]) -> dict:
    """The ``guild_administration`` columns one package resolves to.

    Returned as a plain dict of column values so the caller can put them in the
    same UPDATE as the caps — one row, one write, one transaction. Every
    capability this build knows is decided by the package, including the ones
    it does not mention: absence is withdrawal.
    """
    granted = set(package)
    return {
        "banner_image_enabled": BANNER_IMAGE in granted,
        "support_enabled": HELP_REQUESTS in granted,
        "auth_options": [
            option.value for name, option in _AUTH_OPTIONS.items() if name in granted
        ],
    }


def package_of(
    *,
    banner_image_enabled: bool,
    support_enabled: bool,
    auth_options: Iterable[str] | None,
) -> list[str]:
    """The package a guild currently holds, read back off its switches.

    The inverse of :func:`administration_values`, for the write's response —
    billing reconciles against what it reads back, so it has to be able to see
    what its last package actually became. Takes the three values rather than
    the row, because the billing role's grants are column-scoped and it never
    holds a whole row to pass.
    """
    held = set(auth_options or ())
    names = [name for name, option in _AUTH_OPTIONS.items() if option.value in held]
    if banner_image_enabled:
        names.append(BANNER_IMAGE)
    if support_enabled:
        names.append(HELP_REQUESTS)
    return sorted(names)
