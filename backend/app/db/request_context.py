"""The shapes a request's database context can take.

:func:`app.db.session.set_rls_context` accepts fourteen keyword arguments and
writes thirteen session variables. Most combinations of those arguments are not
a request: a grantee carrying ``current_guild_id``, a platform read carrying a
guild role, a reader-SQL flag with no guild to read. Which combinations are
real has lived in that function's docstring, as prose, enforced by whoever was
reading it.

Here it is the type. A context is exactly one of the classes below. Each names
only the variables it has any business setting; everything else is written
empty, which is what keeps one request's context from reaching the next on a
pooled connection.

Two shapes already existed as their own functions and are described here for
completeness rather than reimplemented — ``set_billing_context`` and
``set_system_guild_context`` in :mod:`app.db.session`.

The classifier is the useful half. :func:`classify` takes the loose keywords
and either returns the shape they form or raises, so the combinations that were
previously just undescribed now fail at the call rather than running with a
context nobody intended.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Union


class ContextShapeError(ValueError):
    """The arguments do not describe any request this system makes."""


@dataclass(frozen=True)
class Unattributed:
    """No user, no guild — workers, seeding, and the deliberate reset.

    Reads whatever the login role's own grants and policies allow and nothing
    more: with no ``current_user_id`` set, every own-row policy matches nothing.
    """


@dataclass(frozen=True)
class Platform:
    """An authenticated request with no guild in it.

    Assumes ``platform_<tier>`` so the request is role-scoped at the database
    rather than running as the bare login role.
    """

    user_id: int
    tier: Optional[str] = None


@dataclass(frozen=True)
class GuildScoped:
    """A request routed into one guild's schema.

    No role travels here. What somebody is in a community is a row, looked up
    by the establishment seam and computed into the ``standing`` below by the
    database; a routing states which community it is in and nothing about who
    the reader is there.

    Nothing here says whether the guild renders real names. That is the
    guild's own column, read by the projection for the guild this context
    names, so a request carries no second answer that could differ from it.
    """

    guild_id: int
    user_id: Optional[int] = None
    #: The seam's ``GuildContext``, present whenever a person is routed.
    standing: object | None = None
    tier: Optional[str] = None
    read_only: bool = False
    satisfied_providers: Optional[Sequence[int] | str] = None
    scope_initiative_id: Optional[int] = None
    via_dashboard_id: Optional[int] = None
    query: bool = False


@dataclass(frozen=True)
class SystemGuild(GuildScoped):
    """Guild-scoped work with **no person behind it**.

    A background sweep, a poller, a lifecycle job. It is a ``GuildScoped``
    context that names itself as unattended, because nothing else about the
    call says so.

    Three helpers route system work into a guild schema and they are not
    interchangeable — this shape, :func:`app.db.session.set_system_guild_context`
    and :func:`app.db.session.guild_schema_context`. Which one a job needs
    depends on what it touches; each function's own docstring says what it
    routes as. ``services/platform/users.py`` uses two of them a few lines
    apart, for two operations on the same guild.
    """


@dataclass(frozen=True)
class PamGrantee:
    """A time-bound grant into a guild the caller does not belong to.

    A grant names the guild it reaches in its own field, and ``guild_id`` is
    not part of this shape. Membership and a grant are recorded separately;
    this class having no field for the other one is what keeps them apart.

    ``settings_guild_id`` is the other half of a pair: break-glass is a content
    grant and a settings grant issued together, and each names the community on
    its own axis. The two must name the same one. The content half is what
    settles the role; the settings half is what the shared tables' own policies
    read.

    It does narrow like any other routed read: the query surface replays a
    request's own context with the reader flag and a scope added, and a
    grantee reaching that surface is replayed the same way a member is.
    """

    pam_guild_id: int
    user_id: Optional[int] = None
    standing: object | None = None
    tier: Optional[str] = None
    read: bool = False
    write: bool = False
    settings_guild_id: Optional[int] = None
    satisfied_providers: Optional[Sequence[int] | str] = None
    scope_initiative_id: Optional[int] = None
    via_dashboard_id: Optional[int] = None
    query: bool = False


@dataclass(frozen=True)
class InstallScoped:
    """An installed app acting in the community it is installed in.

    The install is the principal, routed into ``guild_<id>_app``. ``standing``
    is the ``InstallContext`` the establishment seam built, which names the
    same community and install. A member token also names the member it acts
    for (``member_user_id``) and the purpose they consented to, both carried by
    that context; it is never a person's own routing. It narrows to one
    initiative the way a person's read does; no other narrowing, grant or
    credential value belongs to it.
    """

    guild_id: int
    install_id: int
    standing: object
    token_client_id: Optional[str] = None
    token_scopes: frozenset[str] = frozenset()
    scope_initiative_id: Optional[int] = None
    member_user_id: Optional[int] = None
    token_purpose: Optional[str] = None


@dataclass(frozen=True)
class SettingsGrantee:
    """A settings-only grant routed to one guild's configuration tables."""

    settings_guild_id: int
    user_id: Optional[int] = None
    tier: Optional[str] = None


RequestContext = Union[
    Unattributed,
    Platform,
    GuildScoped,
    SystemGuild,
    PamGrantee,
    SettingsGrantee,
    InstallScoped,
]


#: Keywords that describe how a guild is routed into, which a grant does not
#: do — its read/write level settles the role it gets instead.
_GUILD_ROUTING = ("read_only",)

#: Keywords that narrow a read that is already routed. They only ever remove
#: rows, and a grantee narrows the same way a member does — the query surface
#: replays a request's own context with these added, whichever it was.
_NARROWING = (
    "scope_initiative_id",
    "via_dashboard_id",
    "query",
)

#: Keywords naming a PAM grant.
_PAM = ("pam_guild_id", "pam_read", "pam_write")

#: Keywords naming what an install's token says of it.
_INSTALL_TOKEN = ("token_client_id", "token_scopes", "member_user_id", "token_purpose")

#: Keywords an install routing leaves unset: they describe a person, a grant,
#: a surface, or a routing an install does not take.
_NOT_FOR_AN_INSTALL = (
    "user_id",
    "platform_role",
    "pam_guild_id",
    "pam_read",
    "pam_write",
    "settings_guild_id",
    "read_only",
    "query",
    "via_dashboard_id",
    "satisfied_providers",
    "satisfied_claims",
    "session_amr",
)


def _set(value: object) -> bool:
    """Whether a keyword was given a value that means anything.

    ``None`` and ``False`` read as absent: a caller spelling out
    ``guild_id=None`` alongside a grant is saying the guild is not part of this
    context, which is the same as leaving it out.
    """
    return value is not None and value is not False and value != ()


def _classify_install(kwargs: dict) -> InstallScoped:
    """The one shape an install routing takes, or raise."""
    install_id = kwargs["install_id"]
    guild_id = kwargs.get("guild_id")
    standing = kwargs.get("context")
    named = [k for k in _NOT_FOR_AN_INSTALL if kwargs.get(k)]
    if named:
        raise ContextShapeError(
            f"{', '.join(named)} are not part of an install routing; an "
            "install acts as itself"
        )
    if not _set(guild_id):
        raise ContextShapeError(
            "an install is routed into the community it is installed in"
        )
    if standing is None:
        raise ContextShapeError(
            "routing an install takes the InstallContext the seam builds; call "
            "app.api.deps.establish_install_access instead of set_rls_context"
        )
    if getattr(standing, "install_id", None) != int(install_id) or getattr(
        standing, "guild_id", None
    ) != int(guild_id):
        raise ContextShapeError(
            "an install routing and its context name the same install in the "
            "same community"
        )
    if not kwargs.get("token_client_id"):
        raise ContextShapeError("an install routing names its token's client")
    member_user_id = kwargs.get("member_user_id")
    token_purpose = kwargs.get("token_purpose")
    if token_purpose is not None and member_user_id is None:
        raise ContextShapeError("a purpose belongs to a member token")
    if (
        getattr(standing, "member_user_id", None) != member_user_id
        or getattr(standing, "purpose", None) != token_purpose
    ):
        raise ContextShapeError(
            "a member token's routing and its context name the same member and purpose"
        )
    return InstallScoped(
        guild_id=int(guild_id),
        install_id=int(install_id),
        standing=standing,
        token_client_id=kwargs.get("token_client_id"),
        token_scopes=frozenset(kwargs.get("token_scopes") or ()),
        scope_initiative_id=kwargs.get("scope_initiative_id"),
        member_user_id=None if member_user_id is None else int(member_user_id),
        token_purpose=token_purpose,
    )


def classify(**kwargs) -> RequestContext:
    """The shape these keywords form, or raise.

    Deliberately no stricter than the rules the system already relies on, so
    that every call this codebase actually makes still classifies. What it
    rejects is what was never meant to be expressible.
    """
    guild_id = kwargs.get("guild_id")
    user_id = kwargs.get("user_id")
    tier = kwargs.get("platform_role")
    standing = kwargs.get("context")

    # An installed app is its own principal. Decided first, so a routing that
    # names an install is never read as a community routing with nobody behind
    # it.
    if kwargs.get("install_id") is not None:
        return _classify_install(kwargs)
    if any(kwargs.get(k) for k in _INSTALL_TOKEN) or (
        getattr(standing, "install_id", None) is not None
    ):
        raise ContextShapeError(
            "an install's token values and its context route only with the "
            "install they belong to"
        )

    pam_named = [k for k in _PAM if _set(kwargs.get(k))]
    routing_named = [k for k in _GUILD_ROUTING if _set(kwargs.get(k))]
    narrowing_named = [k for k in _NARROWING if _set(kwargs.get(k))]
    settings_guild_id = kwargs.get("settings_guild_id")

    # Routing a person into a community is the establishment seam's call, and
    # the standing it computes is what the initiative gates read. A routing
    # that names both without one would run every membership leg against an
    # empty standing.
    if _set(guild_id) and _set(user_id) and standing is None:
        raise ContextShapeError(
            "routing a user into a guild takes the GuildContext the seam "
            "builds; call app.api.deps.establish_guild_access instead of "
            "set_rls_context"
        )

    if _set(settings_guild_id):
        if _set(guild_id) or routing_named or narrowing_named:
            raise ContextShapeError(
                "a settings grant is routed separately from membership and "
                "content grants"
            )
        if not pam_named:
            return SettingsGrantee(
                settings_guild_id=int(settings_guild_id), user_id=user_id, tier=tier
            )
        # The pair: falls through to the grant shape below, which records the
        # settings axis beside the content one.
        if int(settings_guild_id) != int(kwargs.get("pam_guild_id") or 0):
            raise ContextShapeError(
                "a grant pair reaches one community, named on both axes"
            )

    if pam_named:
        if _set(guild_id):
            raise ContextShapeError(
                "a PAM grant and a guild context are different things: the "
                "grant is scoped by pam_guild_id, not current_guild_id"
            )
        if not _set(kwargs.get("pam_guild_id")):
            raise ContextShapeError("a PAM grant must name the guild it reaches")
        if routing_named:
            raise ContextShapeError(
                f"{', '.join(routing_named)} say how a guild is routed into; a "
                "grant's read/write level settles that instead"
            )
        return PamGrantee(
            pam_guild_id=int(kwargs["pam_guild_id"]),
            user_id=user_id,
            standing=standing,
            tier=tier,
            read=bool(kwargs.get("pam_read")),
            write=bool(kwargs.get("pam_write")),
            settings_guild_id=(
                int(settings_guild_id) if _set(settings_guild_id) else None
            ),
            satisfied_providers=kwargs.get("satisfied_providers"),
            scope_initiative_id=kwargs.get("scope_initiative_id"),
            via_dashboard_id=kwargs.get("via_dashboard_id"),
            query=bool(kwargs.get("query")),
        )

    if _set(guild_id):
        # No user behind a routed guild context means nobody is asking: a
        # sweep, a poller, a lifecycle job. Same context, named for what it is.
        shape = SystemGuild if not _set(user_id) else GuildScoped
        return shape(
            guild_id=int(guild_id),
            user_id=user_id,
            standing=standing,
            tier=tier,
            read_only=bool(kwargs.get("read_only")),
            satisfied_providers=kwargs.get("satisfied_providers"),
            scope_initiative_id=kwargs.get("scope_initiative_id"),
            via_dashboard_id=kwargs.get("via_dashboard_id"),
            query=bool(kwargs.get("query")),
        )

    if routing_named or narrowing_named:
        raise ContextShapeError(
            f"{', '.join(routing_named + narrowing_named)} need a guild or a "
            "grant to be about"
        )

    if _set(user_id) or _set(tier):
        return Platform(user_id=user_id, tier=tier)

    return Unattributed()
