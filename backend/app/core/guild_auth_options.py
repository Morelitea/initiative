"""What an operator may let one guild decide for itself.

Operator-only, per guild: a guild's own admins read these and can write none of
them. They sit in ``guild_administration`` with the caps and the other
entitlements, not on the guild row.

**Two switches, and neither implies the other.** They were three in a ladder
once, which read them as degrees of one thing. They are two unrelated things
that happened to share a tab:

``providers``
    Which of the deployment's providers this community counts as its own, what
    the groups on them mean — including placing somebody as an **admin** of the
    community — and whether members must arrive that way.

``restrictions``
    The restrictions a community puts on itself: refusing personal API keys,
    and holding members to a shorter session than the deployment asks for.

Most guilds hold neither. A team bringing an identity provider holds the first;
a community answering to an auditor holds both. Nobody gets the second as a
side effect of wanting the first, which is what the old master arrangement did
— ``restrictions`` granted the tab, and the tab carried the API-key and
session cards whether or not anybody meant them.

``require_sign_in`` is gone. Insisting on a provider used to be a grant of its
own, on the reasoning that offering a way in is smaller than mandating one.
That predates community-written group rules: a community holding ``providers``
already decides who is in it and at what rank, which makes the requirement the
smaller of the two powers. Migration 0313 folded it into ``providers`` and
rebuilt the Postgres type without it.

A new kind of auth (SAML, SCIM, a passkey policy) joins this enum, a Postgres
``ALTER TYPE ... ADD VALUE``, and the gate that reads it.
"""

from enum import Enum
from typing import Iterable, Optional


class GuildAuthOption(str, Enum):
    #: May say which of the deployment's providers it counts as its own, where
    #: the people on them land, and whether members must arrive that way.
    providers = "providers"
    #: May refuse personal API keys and shorten the session limit.
    restrictions = "restrictions"


#: Mirrors the Postgres enum type created in migration 0285, extended in 0301
#: and rebuilt in 0313. A value added to one has to be added to the other.
GUILD_AUTH_OPTION_VALUES: tuple[str, ...] = tuple(o.value for o in GuildAuthOption)

#: What a guild gets when nobody has granted it anything — the default a fresh
#: guild is created with, and what ``guild_auth_enabled = false`` meant.
NO_GUILD_AUTH_OPTIONS: tuple[GuildAuthOption, ...] = ()


def effective_options(
    stored: Optional[Iterable[str]],
) -> frozenset[GuildAuthOption]:
    """What a guild holds, from what is stored against it.

    Nothing nests any more, so this only drops the unknown: a label this build
    does not know yet, from a column that is an enum.
    """
    resolved = set()
    for value in stored or ():
        try:
            resolved.add(GuildAuthOption(value))
        except ValueError:
            continue
    return frozenset(resolved)
