"""What an operator may let one guild do about its own sign-in.

Operator-only, per guild: a guild's own admins read these and can write none of
them. They sit in ``guild_administration`` with the caps and the other
entitlements, not on the guild row.

Two today, and they are deliberately separate. Adding a provider is a guild
saying "you may come in this way"; requiring one is a guild saying "you may
come in *only* this way", which binds every member. An operator can grant the
first without the second — a guild that offers its IdP alongside a password is
a different arrangement from one that insists on it.

A new kind of auth (SAML, SCIM, a passkey policy) joins this enum, a Postgres
``ALTER TYPE ... ADD VALUE``, and the gate that reads it.
"""

from enum import Enum


class GuildAuthOption(str, Enum):
    #: May register and edit identity providers of its own.
    providers = "providers"
    #: May require that members reach the guild through one of them.
    require_sign_in = "require_sign_in"


#: Mirrors the Postgres enum type created in migration 0285. A value added to
#: one has to be added to the other.
GUILD_AUTH_OPTION_VALUES: tuple[str, ...] = tuple(o.value for o in GuildAuthOption)

#: What a guild gets when nobody has granted it anything — the default a fresh
#: guild is created with, and what ``guild_auth_enabled = false`` meant.
NO_GUILD_AUTH_OPTIONS: tuple[GuildAuthOption, ...] = ()
