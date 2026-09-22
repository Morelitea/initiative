from datetime import datetime, timezone
from enum import Enum
import json
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.sql import text
from sqlalchemy.orm import validates
from sqlmodel import Field, Index, SQLModel, Enum as SQLEnum, Relationship
from pydantic import ConfigDict

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.user_profile_view import MemberProfile
    from app.models.platform.guild_administration import GuildAdministration


class GuildStatus(str, Enum):
    """Lifecycle status of a guild.

    The first three are operator-set from the platform Guilds tab (platform
    `guilds.manage`) and are freely interchangeable:

    - ``active``: normal operation.
    - ``read_only``: members keep read access to content but writes are denied
      at the Postgres role level (routed into ``guild_<id>_ro``).
    - ``suspended``: members lose all content access and the guild vanishes
      from their guild list. Guild admins keep the settings surface (billing /
      data ownership / danger zone) under all three.

    The fourth is not:

    - ``deleted``: the guild has been deleted and is being retained for
      :data:`~app.services.platform.guild_purge.GUILD_RETENTION_DAYS` before
      it is destroyed. Nobody in the guild reaches it — not even its admins,
      whose settings carve-out is withdrawn, because a deleted guild has no
      billing surface left to reach and its danger zone has already been used.
      It is absent from every member's guild list.

      Reached only through deletion and left only through restore, both of
      which do more than move a column, so it is deliberately not offered in
      the operator's status control and a PATCH that names it is refused.

    PAM/break-glass grants deliberately override all of this: a grantee
    behaves exactly as against an active guild (the resolver's grant branch
    never consults the status), so no status can lock the platform operators
    out — which is what lets an operator look inside a deleted guild before
    deciding whether to bring it back. The status is not serialized to guild
    members.
    """

    active = "active"
    read_only = "read_only"
    suspended = "suspended"
    deleted = "deleted"


#: The statuses from which a request reaches guild content at all. Everything
#: else is refused by the guild-access resolver.
#:
#: Stated once, as a set, because the question is asked in a dozen places and
#: every one of them should have the same answer.
#: ``guild_soft_delete_test`` holds the set and the resolver together.
LIVE_STATUSES: frozenset[GuildStatus] = frozenset(
    {GuildStatus.active, GuildStatus.read_only}
)

#: The statuses an operator may set from the Guilds tab, in the order the
#: control lists them (least → most restrictive). ``deleted`` is absent by
#: derivation rather than by a second hand-written list.
OPERATOR_SETTABLE_STATUSES: tuple[GuildStatus, ...] = (
    GuildStatus.active,
    GuildStatus.read_only,
    GuildStatus.suspended,
)

#: :data:`LIVE_STATUSES` as the strings the column stores, so one set answers
#: the question in Python (``guild.status in LIVE_STATUS_VALUES``) and in SQL
#: (``Guild.status.in_(LIVE_STATUS_VALUES)``) rather than two.
LIVE_STATUS_VALUES: frozenset[str] = frozenset(s.value for s in LIVE_STATUSES)


class GuildCategory(str, Enum):
    """A subject a guild can file itself under in the community directory.

    A closed vocabulary rather than free-form tags: the directory's job is to
    narrow a deployment's guilds down to a browsable shelf, and that only works
    if two guilds about the same thing pick the same word. Guilds choose their
    own (zero or more) from their settings page; the labels are localized
    client-side from these keys, so the stored value is never user-facing text.

    Stored as a ``text[]`` on ``guilds.categories`` with a CHECK that every
    element is one of these, mirroring how ``status`` is a CHECK-constrained
    string rather than a Postgres enum: adding a category is then an ordinary
    migration instead of an enum alteration.
    """

    art = "art"
    gaming = "gaming"
    ttrpg = "ttrpg"
    music = "music"
    writing = "writing"
    education = "education"
    technology = "technology"
    sports = "sports"
    business = "business"
    health = "health"
    social = "social"
    other = "other"


#: What a guild's banner is before anyone touches it: the app's own accent,
#: and white on it. Hard-coded rather than read from the operator's branding —
#: the accent differs between light and dark mode and a banner colour does not,
#: so a guild's banner is its own value from the moment it exists.
DEFAULT_BANNER_COLOR = "#2563eb"

#: Banner text is one of exactly two colours, never a free choice. A banner's
#: fill is the guild's to pick and its artwork can be anything, so the only way
#: the words on it stay readable is to keep them at one end of the scale or the
#: other. Anything in between is a contrast failure waiting for someone to pick
#: it.
BANNER_TEXT_COLORS: tuple[str, str] = ("#ffffff", "#000000")
DEFAULT_BANNER_TEXT_COLOR = BANNER_TEXT_COLORS[0]


class BannerTextAlign(str, Enum):
    """Where a banner's name and description sit across its width.

    Two answers, not a free position: centred reads as a masthead and is what a
    banner with artwork built around a middle wants, while left-aligned lines
    the copy up with the page's own content and is what a photograph with its
    subject on one side wants. Anything finer would be a design tool, and the
    guild is choosing between two looks rather than laying one out.
    """

    center = "center"
    left = "left"


class BannerFade(str, Enum):
    """How far a banner dissolves into the page beneath it.

    ``none`` ends the banner at an edge — a band with the page starting under
    it. The other two extend it past that edge and fade it out there, so the
    page's own content rides over the tail rather than starting below it: a
    ``weak`` fade is a soft join, a ``strong`` one lets the banner read as the
    page's background rather than as a strip on it.
    """

    none = "none"
    weak = "weak"
    strong = "strong"


#: What a banner is before anyone touches it.
DEFAULT_BANNER: dict[str, str] = {
    "color": DEFAULT_BANNER_COLOR,
    "text_color": DEFAULT_BANNER_TEXT_COLOR,
    "text_align": BannerTextAlign.center.value,
    "fade": BannerFade.strong.value,
}

#: The keys a banner has, and the only ones it may have.
BANNER_KEYS: tuple[str, ...] = tuple(DEFAULT_BANNER)


class Guild(SQLModel, table=True):
    __tablename__ = "guilds"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)
    __table_args__ = (
        # The community directory's only query shape: listed guilds, optionally
        # narrowed to one category. Partial on the opt-in so the index stays
        # the size of the directory rather than the size of the deployment.
        Index(
            "ix_guilds_community_categories",
            "categories",
            postgresql_using="gin",
            postgresql_where=text("is_community"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    description: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    banner: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_BANNER),
        sa_column=Column(
            MutableDict.as_mutable(JSONB),
            nullable=False,
            server_default=json.dumps(DEFAULT_BANNER),
        ),
    )
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    # Lifecycle status (see GuildStatus). Stored as a plain string with a CHECK
    # constraint (the access_grants pattern) rather than a Postgres enum.
    #
    # Alone among the operator-set fields it lives here rather than on
    # ``GuildAdministration``: every guild request reads it (suspended -> 403,
    # read_only -> frozen writes) off a guild row the request already loads, so
    # moving it would buy a join on the hottest path in the app.
    status: str = Field(
        default=GuildStatus.active.value,
        sa_column=Column(
            String(16), nullable=False, server_default=GuildStatus.active.value
        ),
    )
    # When the status last changed; NULL until the first operator change.
    status_changed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # Community directory opt-in. False means the guild is reachable only by
    # invite; True publishes its name, description, icon, categories, and roster
    # size to the signed-in directory and lets anyone join without one. Set by
    # the guild's own admins, alongside the identity columns above.
    is_community: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # Whether this guild renders members' real names. On by default, which is
    # what a private workspace expects; off renders handles instead and is the
    # only option for a listed guild — ck_guilds_community_member_names makes
    # that structural, so the effective rule is this one column rather than a
    # pair to reconcile.
    show_member_names: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    # Which shelves the guild files itself under (see GuildCategory). A listed
    # guild must be on at least one — a card nobody can find by browsing is not
    # a listing — which the ck_guilds_community_categories CHECK enforces.
    categories: List[str] = Field(
        default_factory=list,
        sa_column=Column(
            ARRAY(String(32)), nullable=False, server_default=text("'{}'::varchar[]")
        ),
    )
    # Whether this guild is 18+. NULL is the default and stays the answer for
    # almost every guild: it is a question only the directory needs answered,
    # and a guild that never lists itself is never asked it.
    #
    # Listing requires an explicit False — the admin certifies it as part of
    # publishing. True and an unanswered NULL both keep the guild out, which is
    # one CHECK (ck_guilds_community_adult_content) rather than an app rule,
    # because ``IS FALSE`` is false for NULL too.
    has_adult_content: Optional[bool] = Field(
        default=None, sa_column=Column(Boolean, nullable=True)
    )
    # Whether a personal API key may be used against this guild. True by
    # default. False means the guild declines that credential: no key can be
    # minted into it, and a request authenticated by one does not reach it —
    # pinned to this guild or not.
    #
    # Here rather than on ``GuildAuthPolicy`` for the same reason ``status`` is
    # here: the guild-access gate already holds this row, and the answer has to
    # survive a guild lifting its sign-in requirement (which deletes the policy
    # row). Read by the gate, by key creation, and by the cross-guild
    # aggregates.
    allow_api_keys: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    # Whether this guild's members are held to the compliance session standard:
    # they sign in again every ``COMPLIANCE_SESSION_HOURS``, whatever the
    # deployment's own limit says. A single standard rather than a number per
    # guild, so somebody in two of them has one answer and not a comparison.
    #
    # Here for the same reason as the line above: it says what is asked of a
    # session reaching this community, and the answer has to survive the guild
    # lifting its sign-in requirement. Set by the guild's superadmin; read when
    # a sign-in is stamped with its deadline.
    enforce_compliance_session: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # Whether reaching this community asks for a second factor. The community
    # asks for one; which kinds exist, and which providers' word counts as
    # having presented one, are the deployment's answers.
    #
    # Here for the reason the two above are: it says what is asked of a session
    # reaching this community, and the answer has to survive the guild lifting
    # its sign-in requirement. Set by the guild's superadmin; read by the
    # guild-access gate.
    require_second_factor: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # The operator-set caps, plan label, and sign-in entitlement — everything
    # this row is NOT. See GuildAdministration for why they live apart.
    administration: Optional["GuildAdministration"] = Relationship(
        back_populates="guild",
        sa_relationship_kwargs={
            "uselist": False,
            "cascade": "all, delete-orphan",
        },
    )

    members: List["GuildMembership"] = Relationship(
        back_populates="guild",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )

    @validates("is_community")
    def _listing_a_guild_renders_handles(self, _key: str, listed: bool) -> bool:
        """Listing a guild turns its real names off, in the same write.

        ``ck_guilds_community_member_names`` says a listed guild renders
        handles. Doing it here rather than at each caller means the one place
        that sets ``is_community`` is the place it happens, and the constraint
        has nothing left to catch.
        """
        if listed:
            self.show_member_names = False
        return listed


class GuildRole(str, Enum):
    admin = "admin"
    member = "member"
    # Above ``admin``: everything an admin reaches, plus the guild's sign-in
    # configuration — its identity providers and the requirement for entering
    # it. Separated because running a community and holding the keys to who may
    # enter it are different jobs, and most guilds have nobody in this seat.
    #
    # An operator seats the first one; from then on a superadmin may seat
    # another. An ordinary guild admin can do neither — the hand that
    # administers a community is not the hand that decides who may enter it.
    superadmin = "superadmin"
    # A time-bound PAM/support access grantee acting inside a guild they are
    # NOT a member of. Synthesized for the request only — never a persisted
    # ``guild_memberships`` row (the Postgres ``guild_role`` enum has only
    # admin/member, and the member-role endpoints reject assigning it). Unlike
    # ``admin``, ``support`` is bound by its grant's read/write level, enforced
    # at the Postgres role level — a read grant assumes ``guild_<id>_ro``. It
    # is the content axis only: what of the community's configuration a
    # grantee may work is a settings grant, held at its own rung beside this.
    # Break-glass grantees are ``admin``, not this.
    support = "support"


#: Roles that carry a guild admin's authority. ``superadmin`` sits above
#: ``admin``, so anything asking "is this an admin" means "admin or above".
GUILD_ADMIN_ROLES: frozenset[GuildRole] = frozenset(
    {GuildRole.admin, GuildRole.superadmin}
)

#: What an ordinary guild admin may hand out. ``support`` is never persisted at
#: all, and ``superadmin`` is passed on only by somebody already holding it.
GUILD_ASSIGNABLE_ROLES: frozenset[GuildRole] = frozenset(
    {GuildRole.admin, GuildRole.member}
)


#: Roles that exist as ``guild_memberships`` rows. ``support`` is synthesized
#: for the length of a PAM request and never stored, so it is the one value
#: that is not here — derived rather than listed, so a role added to the enum
#: is a stored role unless it is deliberately excluded.
GUILD_STORED_ROLES: frozenset[GuildRole] = frozenset(GuildRole) - {GuildRole.support}


def assignable_roles(by: GuildRole) -> frozenset[GuildRole]:
    """Which roles ``by`` may set on somebody else inside the guild.

    A superadmin passes the seat on; an ordinary admin cannot, and cannot
    take it away either. The *first* one in a guild is seated by an operator
    from platform settings — that is the only part of this a guild cannot do
    for itself.
    """
    if by == GuildRole.superadmin:
        return GUILD_ASSIGNABLE_ROLES | {GuildRole.superadmin}
    return GUILD_ASSIGNABLE_ROLES


class GuildMembership(SQLModel, table=True):
    __tablename__ = "guild_memberships"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)
    __table_args__ = (
        # The primary key is (guild_id, user_id); this is the other direction,
        # for "which guilds is this user in".
        Index("idx_guild_memberships_user_guild", "user_id", "guild_id"),
    )

    guild_id: int = Field(foreign_key="guilds.id", ondelete="CASCADE", primary_key=True)
    user_id: int = Field(foreign_key="users.id", ondelete="CASCADE", primary_key=True)
    role: GuildRole = Field(
        default=GuildRole.member,
        sa_column=Column(
            SQLEnum(GuildRole, name="guild_role"),
            nullable=False,
            server_default=GuildRole.member.value,
        ),
    )
    joined_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    position: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    #: The provider whose claims put this person here, and the only one whose
    #: sign-in may take it away again. NULL is a membership nobody manages —
    #: an invite, a join request, an admin adding somebody — which group sync
    #: neither grants nor reclaims. ``ON DELETE SET NULL``: removing a provider
    #: ends its claim on the row, it does not end the membership.
    oidc_provider_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("auth_providers.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )

    guild: Optional[Guild] = Relationship(back_populates="members")
    user: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(GuildMembership.user_id) == MemberProfile.id",
            "viewonly": True,
        }
    )


class GuildInvite(SQLModel, table=True):
    __tablename__ = "guild_invites"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True, nullable=False, max_length=64)
    guild_id: int = Field(foreign_key="guilds.id", ondelete="CASCADE", nullable=False)
    # The invite outlives the admin who issued it.
    created_by: Optional[int] = Field(
        foreign_key="users.id", ondelete="SET NULL", nullable=True
    )
    expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    max_uses: Optional[int] = Field(default=1, nullable=True)
    uses: int = Field(default=0, nullable=False)
    invitee_email_encrypted: Optional[str] = Field(
        default=None, sa_column=Column(String(2000), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    @property
    def invitee_email(self) -> Optional[str]:
        """Return the decrypted invitee email, or None if not set."""
        if not self.invitee_email_encrypted:
            return None
        from app.core.encryption import decrypt_field, SALT_EMAIL

        return decrypt_field(self.invitee_email_encrypted, SALT_EMAIL)

    guild: Optional[Guild] = Relationship()
