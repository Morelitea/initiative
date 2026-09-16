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

from app.models.platform.guild import CONTENT_ROLES


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

    ``role`` is the *content* role — what ``app.current_guild_role`` carries —
    so it is one of two values whatever the membership row says. Put a stored
    role through ``content_role`` before it gets here.

    Nothing here says whether the guild renders real names. That is the
    guild's own column, read by the projection for the guild this context
    names, so a request carries no second answer that could differ from it.
    """

    guild_id: int
    user_id: Optional[int] = None
    role: Optional[str] = None
    tier: Optional[str] = None
    read_only: bool = False
    satisfied_providers: Optional[Sequence[int] | str] = None
    override_initiatives: tuple[int, ...] = ()
    scope_initiative_id: Optional[int] = None
    via_dashboard_id: Optional[int] = None
    query: bool = False


@dataclass(frozen=True)
class PamGrantee:
    """A time-bound grant into a guild the caller does not belong to.

    A grant names the guild it reaches in its own field, and ``guild_id`` is
    not part of this shape. Membership and a grant are recorded separately;
    this class having no field for the other one is what keeps them apart.

    It does narrow like any other routed read: the query surface replays a
    request's own context with the reader flag and a scope added, and a
    grantee reaching that surface is replayed the same way a member is.
    """

    pam_guild_id: int
    user_id: Optional[int] = None
    tier: Optional[str] = None
    read: bool = False
    write: bool = False
    satisfied_providers: Optional[Sequence[int] | str] = None
    scope_initiative_id: Optional[int] = None
    via_dashboard_id: Optional[int] = None
    query: bool = False


RequestContext = Union[Unattributed, Platform, GuildScoped, PamGrantee]


#: Keywords that describe how a guild is routed into, which a grant does not
#: do — its read/write level settles the role it gets instead.
_GUILD_ROUTING = (
    "guild_role",
    "read_only",
    "override_initiatives",
)

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


def _set(value: object) -> bool:
    """Whether a keyword was given a value that means anything.

    ``None`` and ``False`` read as absent: a caller spelling out
    ``guild_id=None`` alongside a grant is saying the guild is not part of this
    context, which is the same as leaving it out.
    """
    return value is not None and value is not False and value != ()


def classify(**kwargs) -> RequestContext:
    """The shape these keywords form, or raise.

    Deliberately no stricter than the rules the system already relies on, so
    that every call this codebase actually makes still classifies. What it
    rejects is what was never meant to be expressible.
    """
    guild_id = kwargs.get("guild_id")
    user_id = kwargs.get("user_id")
    tier = kwargs.get("platform_role")
    role = kwargs.get("guild_role")

    pam_named = [k for k in _PAM if _set(kwargs.get(k))]
    routing_named = [k for k in _GUILD_ROUTING if _set(kwargs.get(k))]
    narrowing_named = [k for k in _NARROWING if _set(kwargs.get(k))]

    if _set(role) and role not in CONTENT_ROLES:
        raise ContextShapeError(
            f"guild_role {role!r} is not a content role; put a stored role "
            "through content_role() first"
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
            tier=tier,
            read=bool(kwargs.get("pam_read")),
            write=bool(kwargs.get("pam_write")),
            satisfied_providers=kwargs.get("satisfied_providers"),
            scope_initiative_id=kwargs.get("scope_initiative_id"),
            via_dashboard_id=kwargs.get("via_dashboard_id"),
            query=bool(kwargs.get("query")),
        )

    if _set(guild_id):
        return GuildScoped(
            guild_id=int(guild_id),
            user_id=user_id,
            role=role,
            tier=tier,
            read_only=bool(kwargs.get("read_only")),
            satisfied_providers=kwargs.get("satisfied_providers"),
            override_initiatives=tuple(kwargs.get("override_initiatives") or ()),
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
