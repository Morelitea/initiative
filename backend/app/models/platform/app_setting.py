from typing import Optional

from sqlalchemy import ARRAY, Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlmodel import Enum as SQLEnum, Field, SQLModel
from pydantic import ConfigDict

from app.core.login_methods import (
    DEFAULT_LOGIN_METHODS,
    LoginMethod,
    SecondFactorRequirement,
)
from app.models.platform.user_dm_settings import DmPolicy

# Platform OIDC config lives on the provider registry row (``auth_providers``
# slug ``oidc``), not here. Which ways in the deployment permits does — see
# ``login_methods`` below and ``app.services.platform.auth_posture``.


#: ``DEFAULT_LOGIN_METHODS`` as Postgres writes an array literal, so the set is
#: stated once rather than here and in ``login_methods`` below. The migrations
#: that moved this default keep their own copies: a migration is the record of
#: what changed when, and is not read for what the default is now.
_DEFAULT_LOGIN_METHODS_SQL = "{%s}" % ",".join(m.value for m in DEFAULT_LOGIN_METHODS)


#: The retention window a deployment gets until it says otherwise, in days.
#:
#: The figure is the deployment's, not a community's: one answer for everybody
#: on the server, set by whoever runs it. A community cannot shorten or extend
#: its own, which is what makes the window mean something to the person
#: deleting theirs.
DEFAULT_GUILD_RETENTION_DAYS = 90

#: The window a deployment gets for a deleted **account**, in days.
#:
#: Shorter than the community one by default: a community's window protects a
#: body of work that several people made, an account's protects one person
#: from a decision they made in a moment, and thirty days is what somebody
#: takes to change their mind.
#:
#: It is a separate figure from the community's rather than one setting for
#: both, because they answer to different things — what a deployment owes the
#: people in it, and what it owes the person leaving.
DEFAULT_ACCOUNT_RETENTION_DAYS = 30

#: The shortest window a deployment may set, for either. A day, because a
#: window measured in hours is not one somebody notices their mistake inside
#: of.
MIN_GUILD_RETENTION_DAYS = 1

#: The longest. Past this, the answer being asked for is "never", which is what
#: clearing the figure says.
MAX_GUILD_RETENTION_DAYS = 3650


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_settings"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int = Field(default=1, primary_key=True)

    light_accent_color: str = Field(
        default="#2563eb",
        sa_column=Column(String(20), nullable=False, server_default="#2563eb"),
    )
    dark_accent_color: str = Field(
        default="#60a5fa",
        sa_column=Column(String(20), nullable=False, server_default="#60a5fa"),
    )

    # Whether an arriving visitor is asked what this deployment may keep in
    # their browser. Off by default: most deployments are a group's own server,
    # reached by people who were sent a link, and a question nobody needed is
    # just something in the way. An owner running a public front door turns it
    # on. The answer itself lives in that browser and never reaches here —
    # there is no account behind a landing-page visitor to attach it to.
    cookie_consent_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )

    # What this deployment is running, and what it was running before that.
    # A notice that only matters to somebody upgrading past a given release has
    # no way to know that from a publication date — a fresh install of 0.70 was
    # never on 0.64. The pair is rolled forward at boot: when the running
    # version differs from ``last_seen_version``, the old value becomes
    # ``previous_version``. Both are NULL on a fresh install, which is exactly
    # what "never upgraded from anything" looks like.
    last_seen_version: Optional[str] = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )
    previous_version: Optional[str] = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )

    # Which ways in this deployment permits. A Postgres enum array: adding a
    # method later is a value on the type, not a column per method, and the
    # database validates the elements rather than a hand-kept CHECK list. The
    # non-empty constraint is the "at least one" rule — see
    # ``app.core.login_methods``.
    # How long somebody may stay signed in before signing in again, in hours.
    # This is the *absolute* limit; ``AUTH_REFRESH_TTL_DAYS`` is the separate
    # question of how long they may leave the app alone.
    #
    # NULL, the default, asks for no limit — a self-hosted deployment is not
    # answering to anybody, and the idle window already ends a session nobody
    # uses. It also has to be longer than that window to mean anything: set
    # equal to it, the absolute limit always binds first and the idle window
    # stops sliding, so a daily user is signed out on a timer regardless.
    session_max_hours: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )

    # And the other half: the longest a session may be left alone. NULL keeps
    # ``AUTH_REFRESH_TTL_DAYS``, which is where this question was answered
    # before and still is for a deployment that says nothing. A figure here
    # narrows it; a community held to the compliance standard narrows it
    # further. Whichever is strictest binds, which is what a limit means.
    session_idle_minutes: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )

    # How long a deleted community is kept before it is destroyed, in days.
    #
    # NULL is not the default here, unlike the limit above: it means **never**
    # destroy one. A deployment that has undertaken to keep what its members
    # put in it — or that is holding everything pending something unresolved —
    # says so by clearing this, and deleted communities then sit in the
    # operator's list until somebody restores or purges one deliberately.
    #
    # 90 days on a fresh install and on every upgrade, because that is the
    # figure the retention window shipped as.
    # How long a deleted account is kept before it is erased, in days.
    #
    # NULL means never, as it does above: the deployment keeps the account and
    # nothing erases it on a timer. That is the answer for one required to keep
    # accounts rather than to remove them, and the reason this is a setting at
    # all rather than the constant it started as.
    deleted_account_retention_days: Optional[int] = Field(
        default=DEFAULT_ACCOUNT_RETENTION_DAYS,
        sa_column=Column(
            Integer, nullable=True, server_default=str(DEFAULT_ACCOUNT_RETENTION_DAYS)
        ),
    )

    deleted_community_retention_days: Optional[int] = Field(
        default=DEFAULT_GUILD_RETENTION_DAYS,
        sa_column=Column(
            Integer, nullable=True, server_default=str(DEFAULT_GUILD_RETENTION_DAYS)
        ),
    )
    login_methods: list[str] = Field(
        default_factory=lambda: [m.value for m in DEFAULT_LOGIN_METHODS],
        sa_column=Column(
            ARRAY(PGEnum(LoginMethod, name="login_method", create_type=False)),
            nullable=False,
            server_default=_DEFAULT_LOGIN_METHODS_SQL,
        ),
    )

    # Who this deployment asks to hold a second factor. A Postgres enum for
    # the same reason ``login_methods`` is one: the database validates the
    # value, and a rung added later is a value on the type rather than a
    # column here. ``nobody`` on every fresh and upgraded install, so an
    # upgrade asks nothing of anybody it was not already asking.
    #
    # What answers it is the account holding one — a confirmed authenticator
    # or a registered passkey — or a session that presented one, which is what
    # an identity provider's own second factor looks like from here. The
    # per-session reading is a community's question (``require_methods``);
    # this one is about the account.
    second_factor_requirement: SecondFactorRequirement = Field(
        default=SecondFactorRequirement.nobody,
        sa_column=Column(
            PGEnum(
                SecondFactorRequirement,
                name="second_factor_requirement",
                create_type=False,
            ),
            nullable=False,
            server_default=SecondFactorRequirement.nobody.value,
        ),
    )

    smtp_host: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    smtp_port: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    smtp_secure: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    smtp_reject_unauthorized: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    smtp_username: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    smtp_password_encrypted: Optional[str] = Field(
        default=None, sa_column=Column(String(2000), nullable=True)
    )
    smtp_from_address: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    smtp_test_recipient: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )

    # Whether this deployment runs a community directory at all: the browsable
    # list of guilds that have opted in, and the invite-free join that goes with
    # it. Off until an owner turns it on, so a deployment that never wanted a
    # public front door does not grow one on upgrade.
    community_directory_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )

    # Whether an account must say it is 16 or older before it joins a guild
    # listed in that directory. It gates that join and nothing else — a
    # private guild is its own to answer for, and asks nobody's age.
    # On by default, and only a platform owner
    # turns it off — doing so is that owner asserting that every account on the
    # deployment already belongs to an adult, which is a thing an enterprise
    # rollout knows and a public one does not. Independent of the directory
    # switch above so the assertion survives the directory being toggled.
    community_age_gate_enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )

    # Whether this deployment offers direct messages at all -- My Messages,
    # and every connection and message request that feeds it. On by default, so
    # a deployment that upgrades into it keeps the messaging its people are
    # already using; a platform owner turns it off for somewhere messaging does
    # not belong. Switching it off keeps every channel and policy exactly as it
    # was, so switching it back on restores them rather than rebuilding them.
    direct_messages_enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )

    # The direct-message policy a newly created account starts on. Read once,
    # when the account is created, and copied into its ``user_dm_settings`` row;
    # changing it later moves nobody, so raising it opens no existing account
    # and lowering it revokes no channel anybody is using.
    default_dm_policy: DmPolicy = Field(
        default=DmPolicy.private,
        sa_column=Column(
            SQLEnum(DmPolicy, name="user_dm_policy", create_type=False),
            nullable=False,
            server_default=DmPolicy.private.value,
        ),
    )

    # Whether a notification may reach a phone at all. On by default, which is
    # what every deployment has had. Off means this deployment sends none: no
    # push leaves it, the registration endpoint declines, and the device tokens
    # it was holding are dropped, so switching it off is the whole answer rather
    # than the delivery half of one. Devices register again when it comes back.
    push_notifications_enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )

    # And the other place a notification lands: a mailbox. Off means no
    # notification email is written, on any cadence. It is the *notification*
    # half of email and nothing else — a sign-in code, an address to confirm, a
    # password reset and the notices an account gets about itself are not
    # notifications and keep going, because switching this off must not lock
    # anybody out of their account.
    email_notifications_enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )

    # Whether a notification that leaves the app may say what it is about. Off
    # by default: a push that reads "Ana mentioned you in Q3 budget" is the one
    # worth sending. On, a notification that leaves reduces to the kind of thing
    # that happened — "You were mentioned in a comment" — and the app is where
    # the rest of it is. The bell inside the app is unaffected either way.
    redact_notification_content: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )

    # AI config ownership mode: "platform" (the operator's connections apply to
    # every guild), "guild" (each guild admin configures its own), or "disabled".
    # Provider config itself lives in platform_ai_connections /
    # guild_ai_connections; only the global mode lives here. Whether members may
    # attach their own key is a per-connection setting (allow_member_keys on the
    # connection), not a global toggle.
    ai_config_mode: str = Field(
        default="disabled",
        sa_column=Column(String(20), nullable=False, server_default="disabled"),
    )
    # Monotonic counter bumped on every operator AI-config write (mode or
    # platform connection). Read on the request's own (guild) session as the
    # cross-worker cache-freshness signal, so a change is picked up by every
    # replica at once instead of after a per-process TTL.
    ai_config_version: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )

    # Object storage (blob backend). "local" = filesystem under UPLOADS_DIR;
    # "s3" = any S3-compatible store. Seeded from the STORAGE_BACKEND / S3_* env
    # vars on first creation, then DB-authoritative (see app_settings service).
    storage_backend: str = Field(
        default="local",
        sa_column=Column(String(20), nullable=False, server_default="local"),
    )
    s3_bucket: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    s3_region: str = Field(
        default="us-east-1",
        sa_column=Column(String(64), nullable=False, server_default="us-east-1"),
    )
    s3_endpoint_url: Optional[str] = Field(
        default=None, sa_column=Column(String(1000), nullable=True)
    )
    s3_access_key_id: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    s3_secret_access_key_encrypted: Optional[str] = Field(
        default=None, sa_column=Column(String(2000), nullable=True)
    )
    s3_use_path_style: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    s3_kms_key_id: Optional[str] = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    s3_local_fallback: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )

    # The guild that receives this deployment's operations work — security,
    # moderation, support and feedback cases. NULL on every fresh and existing
    # install, which is what "this deployment routes nothing" looks like: the
    # writer resolves no binding and every call it makes is a no-op.
    #
    # An ordinary guild in every other respect. Which project each stream lands
    # in is per-guild config inside it (``intake_bindings``), so the platform
    # holds a pointer and no second copy of the tooling.
    operations_guild_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="SET NULL"), nullable=True
        ),
    )
