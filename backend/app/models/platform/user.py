from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Enum as SQLEnum, Field, SQLModel, Relationship
from pydantic import ConfigDict


if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.guild import GuildMembership


class UserRole(str, Enum):
    """Platform-level (app-wide) user role.

    Ordered from least to most privileged. Authorization checks should
    generally go through the capability model (``app.core.capabilities``)
    rather than comparing roles directly, so that the privilege ladder can
    evolve without touching every call site.
    """

    member = "member"
    support = "support"
    moderator = "moderator"
    operator = "operator"
    owner = "owner"


class UserStatus(str, Enum):
    active = "active"
    #: Frozen by a platform moderator. Distinct from ``deactivated``, which
    #: drops every guild and initiative membership — suspension writes this one
    #: column and nothing else, so lifting it restores the account whole. The
    #: holder still signs in and reaches their own account; what they lose is
    #: every guild.
    suspended = "suspended"
    #: The holder closed their account. Memberships are dropped; the row and
    #: its personal data remain so an administrator can reactivate it.
    deactivated = "deactivated"
    #: Erased. The row is a husk kept only so the work it touched still says
    #: who did it.
    anonymized = "anonymized"


class Presence(str, Enum):
    """How a person appears to everyone else.

    Both halves of one idea, which is why it is one enum: what a person picks
    for themselves, and what a reader of their name is shown. The picked value
    is a standing preference on the account; the shown value is that preference
    narrowed by what the process can see — whether they have Initiative open at
    all, and whether anyone has touched it lately — which is decided in one
    place (``app.services.platform.presence``).

    ``idle`` is the one a person may either pick or be given: left on
    ``online``, an account that goes quiet is shown it anyway, and picking it
    outright is how someone says they would rather look that way regardless.

    Not to be confused with ``UserStatus`` (the account's standing, which is not
    the account holder's to write) or ``custom_status`` (the line they wrote).
    """

    #: Follow the connection: shown while a tab is open, and not otherwise.
    online = "online"
    #: Open, but with no sign of anyone at the keyboard for a while — the
    #: state for stepping away, whether or not you said so. The one that is
    #: inferred as well as picked: it is what ``online`` becomes on its own
    #: after a long enough quiet, and what someone picks to look that way
    #: whether or not they are.
    idle = "idle"
    #: Here, and would rather not be interrupted.
    busy = "busy"
    #: Shown to nobody, whether or not a tab is open. Also what a reader is
    #: told about anyone who has nothing open.
    offline = "offline"


#: The statuses that may hold a session. A suspended account signs in — that is
#: how its holder reaches their own account, and how they can be told why —
#: and is stopped at every guild instead.
LOGIN_STATUSES: frozenset[UserStatus] = frozenset(
    {UserStatus.active, UserStatus.suspended}
)


class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = (
        # A handle is unique as a pair, and case-insensitively on the name
        # part: one never differs from another by case alone.
        Index(
            "ix_users_handle",
            text("lower(username)"),
            "discriminator",
            unique=True,
        ),
        # The bound on the status line, held where the line is stored as well
        # as where it is parsed — see
        # ``app.schemas.platform.user.STATUS_TEXT_MAX_LENGTH``.
        CheckConstraint(
            "char_length(custom_status->>'text') <= 40",
            name="ck_users_custom_status_text_length",
        ),
    )
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
    __allow_unmapped__ = True

    id: Optional[int] = Field(default=None, primary_key=True)
    email_hash: str = Field(sa_column=Column(String(64), unique=True, nullable=False))
    email_encrypted: str = Field(sa_column=Column(String(2000), nullable=False))
    #: The name part of this account's handle — what a person picks and reads.
    #: Unique with ``discriminator``, case-insensitively (``ix_users_handle``);
    #: the vocabulary lives in ``app.core.usernames``.
    username: str = Field(sa_column=Column(String(32), nullable=False))
    #: The number behind the name, 0000-9999, drawn at random and rendered
    #: zero-padded beside it. Never chosen by anyone.
    discriminator: int = Field(sa_column=Column(SmallInteger, nullable=False))
    #: Whether the handle was picked rather than assigned. False on a row the
    #: backfill seeded and on an account provisioned from SSO claims, which is
    #: what routes its owner to the pick screen on their next sign-in.
    username_chosen: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    full_name: Optional[str] = Field(default=None)
    # NULL = no password set (SSO-only account) — password verification treats
    # a missing hash as "never a match", so such an account can only sign in
    # through its identity provider until it explicitly sets a password.
    hashed_password: Optional[str] = Field(default=None)
    role: UserRole = Field(
        default=UserRole.member,
        sa_column=Column(
            SQLEnum(UserRole, name="user_role"),
            nullable=False,
            server_default=UserRole.member.value,
        ),
    )
    status: UserStatus = Field(
        default=UserStatus.active,
        sa_column=Column(
            SQLEnum(UserStatus, name="user_status"),
            nullable=False,
            server_default=UserStatus.active.value,
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    #: Where this user's picture is: a path this API serves
    #: (``/api/v1/users/{id}/avatar/{sha256}``, bytes in ``user_avatars``) or a
    #: URL somewhere else, from an OIDC ``picture`` claim. One or the other,
    #: never both — see ``app.services.platform.user_avatars``.
    avatar_url: Optional[str] = Field(default=None, nullable=True)
    token_version: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default="1"),
    )
    #: What this person is up to, in their own words: an emoji, a short line,
    #: or both, as ``{"emoji": ..., "text": ...}``. One column rather than two,
    #: because it is one thing a person sets and one thing every surface that
    #: names them renders. Distinct from ``status`` above, which is the
    #: account's standing and is not theirs to write. The shape is
    #: ``app.schemas.platform.user.CustomStatus``.
    custom_status: dict = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    #: How this person wants to appear to everyone else — see ``Presence``.
    #: A standing preference rather than live state: the live half is which
    #: sockets are open, which no column could hold.
    presence: Presence = Field(
        default=Presence.online,
        sa_column=Column(
            SQLEnum(Presence, name="user_presence"),
            nullable=False,
            server_default=Presence.online.value,
        ),
    )
    #: How this person's profile is dressed: a banner, a frame around the
    #: picture, trophies under it. Each is an id naming a catalog entry
    #: the client resolves to artwork it already ships — never an upload, so a
    #: decorated profile costs a guild none of its storage. The shape is
    #: ``app.schemas.platform.user.ProfileDecorations``.
    profile_decorations: dict = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    week_starts_on: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    # How many recently-opened items the header tabs bar keeps and shows for
    # this user, across all entity types and guilds. Drives both the display
    # count and the per-guild prune cap (see app.services.recent_views).
    # Clamped to [1, 100] on write; default 20 preserves the historic behavior.
    recent_tabs_limit: int = Field(
        default=20,
        sa_column=Column(Integer, nullable=False, server_default="20"),
    )
    email_verified: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    #: When this account said it belongs to somebody at least 13 years old.
    #: NULL means it never has. A timestamp rather than a flag because the
    #: record of *when* is the point: it is what a deployment running a
    #: community directory keeps for every account in a listed guild.
    #: Whether it is asked for at all is the platform owner's switch
    #: (``AppSetting.community_age_gate_enabled``).
    age_confirmed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    timezone: str = Field(
        default="UTC",
        sa_column=Column(String(64), nullable=False, server_default="UTC"),
    )
    overdue_notification_time: str = Field(
        default="21:00",
        sa_column=Column(String(5), nullable=False, server_default="21:00"),
    )
    email_initiative_addition: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    email_task_assignment: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    email_project_added: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    email_overdue_tasks: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    email_mentions: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    # Reactions get their own gate rather than riding on ``*_mentions``: a
    # reaction is a far lighter signal than being named, and someone who wants
    # to hear about mentions may well not want to hear about every thumbs-up.
    email_comment_reactions: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    push_initiative_addition: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    push_task_assignment: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    push_project_added: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    push_overdue_tasks: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    push_mentions: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    push_comment_reactions: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    email_events: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    push_events: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    email_event_reminders: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    push_event_reminders: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    # Lead time (minutes) for the scheduled event reminder. NULL = reminders off.
    event_reminder_minutes_before: Optional[int] = Field(
        default=15,
        sa_column=Column(Integer, nullable=True, server_default="15"),
    )
    last_overdue_notification_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_task_assignment_digest_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # Locale
    locale: str = Field(
        default="en",
        sa_column=Column(String(10), nullable=False, server_default="en"),
    )

    # UI Preferences
    color_theme: str = Field(
        default="kobold",
        sa_column=Column(String(50), nullable=False, server_default="kobold"),
    )
    # Stored as a free-form short string; the frontend interprets the value
    # against a fixed enum (none | confetti | heart | d20 | gold_coin | random)
    # and falls back to "none" if it doesn't recognise the value. Scoped to
    # "visual" so audio / haptic siblings can be added later as their own
    # columns without renaming this one.
    task_completion_visual_feedback: str = Field(
        default="none",
        sa_column=Column(String(32), nullable=False, server_default="none"),
    )
    # Subtler siblings to the visual effect — these fire on any task the
    # current user marks done (assignee check is dropped because they're
    # less obtrusive). Default on so existing users discover them.
    task_completion_audio_feedback: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    task_completion_haptic_feedback: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )

    @property
    def email(self) -> str:
        """Return the decrypted email address. Used by schema serialization."""
        from app.core.encryption import decrypt_field, SALT_EMAIL

        return decrypt_field(self.email_encrypted, SALT_EMAIL)

    # An account has no standing view of guild content. What refers to a person
    # from inside a guild schema — an assignment, a membership, an ordering, a
    # favourite — is reached from that content, through ``MemberProfile``, on a
    # session routed into the guild that holds it. ``hard_delete_user`` clears
    # those rows itself, guild by guild.
    #
    # ``guild_memberships`` is the exception, and stays: it is a ``public``
    # table, and the cascade here is what removes a deleted account's
    # memberships.
    guild_memberships: List["GuildMembership"] = Relationship(
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    api_keys: List["UserApiKey"] = Relationship(back_populates="user")


from app.models.platform.api_key import UserApiKey  # noqa: E402  # isort:skip
