"""What an operator may let one guild do about its own sign-in.

Operator-only, per guild: a guild's own admins read these and can write none of
them. They sit in ``guild_administration`` with the caps and the other
entitlements, not on the guild row.

``restrictions`` is the master, and it is what most guilds never hold: without
it a guild has no Authentication surface at all — no providers it counts as
its own, no sign-in requirement, no refusing personal API keys, no session standard. Nobody
running a book club is asked to think about any of it.

The two beneath it are deliberately separate. Connecting a provider is a guild
saying "you may come in this way"; requiring one is a guild saying "you may
come in *only* this way", which binds every member. An operator can grant the
first without the second — a guild that offers its IdP alongside a password is
a different arrangement from one that insists on it.

A new kind of auth (SAML, SCIM, a passkey policy) joins this enum, a Postgres
``ALTER TYPE ... ADD VALUE``, and the gate that reads it — underneath the
master, like the two that are here.
"""

from enum import Enum
from typing import Iterable, Optional


class GuildAuthOption(str, Enum):
    #: May configure its own sign-in at all. The master: everything below hangs
    #: off it, and so does every auth surface that has no option of its own.
    restrictions = "restrictions"
    #: May say which of the deployment's providers it counts as its own.
    providers = "providers"
    #: May require that members reach the guild through one of them.
    require_sign_in = "require_sign_in"


#: Mirrors the Postgres enum type created in migration 0285 and extended in
#: 0301. A value added to one has to be added to the other.
GUILD_AUTH_OPTION_VALUES: tuple[str, ...] = tuple(o.value for o in GuildAuthOption)

#: What a guild gets when nobody has granted it anything — the default a fresh
#: guild is created with, and what ``guild_auth_enabled = false`` meant.
NO_GUILD_AUTH_OPTIONS: tuple[GuildAuthOption, ...] = ()


def effective_options(
    stored: Optional[Iterable[str]],
) -> frozenset[GuildAuthOption]:
    """What a guild holds, from what is stored against it.

    A tick underneath the master counts for nothing until the master itself is
    granted, so this is where the nesting is applied — once, for every gate and
    for the community's own settings page alike, rather than at each of them.

    Unknown values are dropped: the column is an enum, so this is the read of a
    label this build does not know yet.
    """
    resolved = set()
    for value in stored or ():
        try:
            resolved.add(GuildAuthOption(value))
        except ValueError:
            continue
    if GuildAuthOption.restrictions not in resolved:
        return frozenset()
    return frozenset(resolved)
