"""The ways a person may sign in to this deployment.

The canonical set. ``app_settings.login_methods`` stores a subset of it as a
Postgres enum array, the settings surface renders one checkbox per member, and
the frontend mirrors these values (kept honest by a drift test). Adding a
method — passkeys, magic-link — is a value here, a Postgres ``ALTER TYPE ... ADD
VALUE``, and a refusal point; no column and no schema reshaping.

A *method* is a way of proving who you are at the start of a session. Device
tokens and API keys are not members: they are credentials derived from a
sign-in that already happened, so disabling a method must never invalidate one.
"""

from enum import Enum


class LoginMethod(str, Enum):
    #: Email/username + password, against the local hash.
    password = "password"
    #: Any configured identity provider — the whole ``auth_providers``
    #: registry, operator-global and guild-scoped alike. Per-provider
    #: ``enabled`` does the finer-grained work; this says whether the
    #: deployment permits the route at all.
    sso = "sso"
    #: An authenticator app's code, presented after a password. Unlike the two
    #: above it cannot open a session by itself — it accompanies one that has
    #: already been proved, which is why :data:`PRIMARY_LOGIN_METHODS` exists.
    totp = "totp"
    #: A WebAuthn credential held by a device or a password manager, answering
    #: a prompt instead of a typed password. Opens a session by itself, and is
    #: bound to this deployment's own domain.
    passkey = "passkey"


#: Mirrors the Postgres enum type created in migration 0284, extended in 0291
#: and 0314. A value added to one has to be added to the other.
LOGIN_METHOD_VALUES: tuple[str, ...] = tuple(m.value for m in LoginMethod)

#: The methods that can start a session on their own.
#:
#: "At least one method must stay permitted" was the rule while every member
#: could. A second factor accompanies a sign-in rather than beginning one, so
#: the rule is now "at least one of these" — a deployment left with only
#: ``totp`` would offer no way to begin.
PRIMARY_LOGIN_METHODS: tuple[LoginMethod, ...] = (
    LoginMethod.password,
    LoginMethod.sso,
    LoginMethod.passkey,
)

#: What a deployment that has never chosen permits: everything it could.
#: Also the column's server default, so an upgrade changes nobody's behaviour.
DEFAULT_LOGIN_METHODS: tuple[LoginMethod, ...] = (
    LoginMethod.password,
    LoginMethod.sso,
    LoginMethod.totp,
    LoginMethod.passkey,
)
