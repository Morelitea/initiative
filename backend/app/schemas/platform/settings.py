from typing import Annotated, List, Literal, Optional

from pydantic import ConfigDict, EmailStr, Field, field_validator

from app.core.login_methods import LoginMethod, SecondFactorRequirement
from app.core.user_input_validators import validate_provider_slug
from app.models.platform.app_setting import (
    MAX_GUILD_RETENTION_DAYS,
    MIN_GUILD_RETENTION_DAYS,
)
from app.models.platform.user_dm_settings import DmPolicy
from app.schemas.base import RawTextStr, SanitizedBaseModel


class AuthProviderAdminRead(SanitizedBaseModel):
    """One registry provider for the operator admin — never the secret."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    slug: str
    display_name: str
    kind: str
    enabled: bool
    issuer: Optional[str] = None
    client_id: Optional[str] = None
    scopes: Optional[str] = None
    role_claim_path: Optional[str] = None
    allow_jit: bool
    #: Whether communities may connect to this provider. Off keeps one
    #: registered for a single customer out of everybody else's picker.
    icon: Optional[str] = None
    button_style: Optional[str] = None
    # Whether a client secret is stored (write-only; its value is never read
    # back on any request path).
    secret_set: bool = False
    #: Where this provider sends the browser back. Shown so an operator can
    #: register it with their IdP; it remains fixed for the provider's lifetime
    #: because the slug is immutable.
    callback_url: str = ""


def _validate_https_issuer(value: str) -> str:
    """https-only, matching discovery's rule — surfaced at write time instead
    of as a stray error mid-login."""
    if not value.startswith("https://") or len(value) <= len("https://"):
        raise ValueError("issuer must be an https:// URL")
    return value


class AuthProviderCreate(SanitizedBaseModel):
    """A new operator-global login provider. Complete rows only — the login
    flow refuses config-incomplete providers, so the CRUD does too."""

    slug: str = Field(max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    kind: Literal["oidc"] = "oidc"
    enabled: bool = True
    issuer: str
    client_id: str = Field(min_length=1)
    client_secret: Optional[RawTextStr] = None  # None = public / PKCE-only
    scopes: Optional[str] = Field(default="openid email profile", max_length=512)
    role_claim_path: Optional[str] = Field(default=None, max_length=256)
    allow_jit: bool = True
    icon: Optional[str] = Field(default=None, max_length=64)
    button_style: Optional[str] = Field(default=None, max_length=64)

    @field_validator("slug")
    @classmethod
    def _slug_shape(cls, value: str) -> str:
        return validate_provider_slug(value)

    @field_validator("issuer")
    @classmethod
    def _issuer_https(cls, value: str) -> str:
        return _validate_https_issuer(value)


class AuthProviderUpdate(SanitizedBaseModel):
    """Partial update. ``client_secret``: absent = keep, empty = clear,
    value = replace. The slug is immutable — it is the identity the login
    URLs, flow states, and linked identities hang off."""

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    enabled: Optional[bool] = None
    issuer: Optional[str] = None
    client_id: Optional[str] = Field(default=None, min_length=1)
    client_secret: Optional[RawTextStr] = None
    scopes: Optional[str] = Field(default=None, max_length=512)
    role_claim_path: Optional[str] = Field(default=None, max_length=256)
    allow_jit: Optional[bool] = None
    icon: Optional[str] = Field(default=None, max_length=64)
    button_style: Optional[str] = Field(default=None, max_length=64)

    @field_validator("display_name", "issuer", "client_id", "enabled", "allow_jit")
    @classmethod
    def _no_explicit_null(cls, value, info):
        """Absent means keep; an explicit null would strip config a login-ready
        row requires (the login flow refuses config-incomplete providers)."""
        if value is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return value

    @field_validator("issuer")
    @classmethod
    def _issuer_https(cls, value: Optional[str]) -> Optional[str]:
        return _validate_https_issuer(value) if value is not None else value


class AuthProviderDiscoverRequest(SanitizedBaseModel):
    """An address to look up before anything is saved."""

    issuer: str

    @field_validator("issuer")
    @classmethod
    def _issuer_https(cls, value: str) -> str:
        return _validate_https_issuer(value)


class AuthProviderProbeResult(SanitizedBaseModel):
    """What one look at a provider found.

    Named fields only. The document itself and the status that carried it stay
    server-side; ``error_code`` is what a failure says, and the detail behind
    it is in the log.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    ok: bool
    error_code: Optional[str] = None
    #: Trimmed of a pasted ``.well-known`` suffix, so the form can correct
    #: what somebody copied.
    issuer: Optional[str] = None
    authorization_endpoint: Optional[str] = None
    token_endpoint: Optional[str] = None
    jwks_uri: Optional[str] = None
    userinfo_endpoint: Optional[str] = None
    signing_algs: List[str] = Field(default_factory=list)
    #: What the provider says it offers. Advisory — these fill in the scopes
    #: and groups-claim fields, and no login decision reads them.
    scopes_supported: List[str] = Field(default_factory=list)
    claims_supported: List[str] = Field(default_factory=list)
    #: Where a provider in this namespace sends the browser back, with
    #: ``{slug}`` still to fill in. Computed here rather than guessed by the
    #: caller: it is built from the deployment's own ``APP_URL``, which is what
    #: the finished provider's callback is built from too, and the address has
    #: to match exactly at the far end. Returned by the look-up because that is
    #: when somebody is about to need it.
    callback_url_template: str = ""


class ConnectableProviderRead(SanitizedBaseModel):
    """One provider a community may connect to, as the community sees it.

    Deliberately less than the operator's view: a community picks a provider by
    name. It holds no issuer and no client id, so it is shown neither — which
    also keeps one customer's identity provider out of another's list.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    display_name: str
    icon: Optional[str] = None
    #: False where the operator has switched it off or left it half
    #: configured — said here so a community is not offered a button that
    #: cannot work.
    login_ready: bool = True


#: One value a narrowing counts, bounded to what the column holds so an
#: over-long one is answered with a validation error rather than a database
#: one. The list is bounded too: a narrowing names a tenant, not a directory.
ClaimValue = Annotated[str, Field(max_length=256)]
MAX_CLAIM_VALUES = 64


class GuildProviderConnectionRead(SanitizedBaseModel):
    """One community signing its members in through one provider.

    Also how an arrangement the community has not made itself is shown: the
    deployment's default for that provider, marked ``inherited``, which the
    community replaces by connecting to the provider itself.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: Null on an inherited arrangement — there is no row of this community's
    #: to edit until it makes one.
    id: Optional[int] = None
    #: Whether this is the deployment's answer rather than the community's.
    inherited: bool = False
    provider_id: int
    provider_slug: str
    provider_display_name: str
    provider_icon: Optional[str] = None
    #: Which verified claim decides whether somebody belongs here — ``hd`` for
    #: a Google Workspace domain, ``tid`` for an Entra tenant. Null with an
    #: empty ``claim_values`` is unnarrowed, which is right where the provider
    #: is already the community's own.
    claim: Optional[str] = None
    claim_values: List[str] = Field(default_factory=list)
    enabled: bool
    #: Whether somebody this connection counts as theirs joins on arrival.
    auto_join: bool = False
    login_ready: bool = True


class GuildProviderConnectionCreate(SanitizedBaseModel):
    """Connect to one of the providers on offer."""

    provider_id: int
    claim: Optional[str] = Field(default=None, max_length=64)
    claim_values: Optional[List[ClaimValue]] = Field(
        default=None, max_length=MAX_CLAIM_VALUES
    )
    enabled: bool = True
    #: Whether somebody this connection counts as theirs joins on arrival.
    auto_join: bool = False


class GuildProviderConnectionUpdate(SanitizedBaseModel):
    """Change the narrowing, or take the button away. The provider a
    connection is to is not editable: pointing it elsewhere would change who
    gets in without saying so. Disconnect and connect instead."""

    claim: Optional[str] = Field(default=None, max_length=64)
    claim_values: Optional[List[ClaimValue]] = Field(
        default=None, max_length=MAX_CLAIM_VALUES
    )
    enabled: Optional[bool] = None
    auto_join: Optional[bool] = None


class PlatformProviderDefaultRead(SanitizedBaseModel):
    """How one provider is arranged for a community that has not said."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    provider_id: int
    claim: Optional[str] = None
    claim_values: List[str] = Field(default_factory=list)
    enabled: bool = True


class PlatformProviderDefaultUpdate(SanitizedBaseModel):
    """Answer for a provider on behalf of the communities that have not.

    Carries the arrangement and nothing else. There is no ``auto_join`` here:
    a default names a provider, never a community, so who joins a community
    stays that community's to say.
    """

    claim: Optional[str] = Field(default=None, max_length=64)
    claim_values: Optional[List[ClaimValue]] = Field(
        default=None, max_length=MAX_CLAIM_VALUES
    )
    enabled: Optional[bool] = None


class GuildClaimRuleRead(SanitizedBaseModel):
    """One rule a community wrote: a group this provider asserts, and where
    somebody carrying it lands."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    provider_id: int
    provider_display_name: str
    provider_icon: Optional[str] = None
    claim_value: str
    guild_role: str
    initiative_id: Optional[int] = None
    initiative_name: Optional[str] = None
    initiative_role_id: Optional[int] = None
    initiative_role_name: Optional[str] = None


class GuildClaimRuleCreate(SanitizedBaseModel):
    """Place the people carrying one group.

    Naming an initiative places them there as well as in the community, since
    somebody has to be in the community to be in one of its initiatives.
    """

    provider_id: int
    claim_value: str = Field(max_length=500)
    guild_role: str = "member"
    initiative_id: Optional[int] = None
    initiative_role_id: Optional[int] = None


class GuildClaimRuleUpdate(SanitizedBaseModel):
    """Change where a group lands. Its provider is not editable: a group value
    means nothing without knowing who asserted it, so a rule pointed at
    another provider is a different rule."""

    claim_value: Optional[str] = Field(default=None, max_length=500)
    guild_role: Optional[str] = None
    initiative_id: Optional[int] = None
    initiative_role_id: Optional[int] = None


class GuildClaimRulesResponse(SanitizedBaseModel):
    """The rules, and whether the providers behind them report groups at all.

    Which claim carries groups is the operator's to set per provider. A
    community can write rules against a provider that has none, and they will
    never match anything, so the surface says which of its connections are
    ready to be written against rather than letting somebody find out later.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    rules: List[GuildClaimRuleRead] = Field(default_factory=list)
    #: Provider ids this community connects to that report groups.
    reporting_provider_ids: List[int] = Field(default_factory=list)


class OIDCSettingsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    enabled: bool
    issuer: Optional[str] = None
    client_id: Optional[str] = None
    redirect_uri: Optional[str] = None
    post_login_redirect: Optional[str] = None
    mobile_redirect_uri: Optional[str] = None
    provider_name: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)


class LoginMethodStatus(SanitizedBaseModel):
    """One way in, and what withdrawing it would cost."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    method: LoginMethod
    enabled: bool
    #: Whether this method can begin a session on its own. False for a second
    #: factor, which accompanies a sign-in rather than opening one — the one
    #: distinction that decides where the surface asks about it, so it is
    #: derived from ``PRIMARY_LOGIN_METHODS`` here rather than listed again
    #: in the frontend.
    primary: bool
    #: Whether this method can answer a second-factor requirement. Derived
    #: from ``FACTOR_METHODS``, and orthogonal to ``primary``: a passkey is
    #: both — a way in on its own, and an answer to being asked for a factor.
    answers_factor: bool = False
    #: Accounts that can sign in today and could not if this method were
    #: withdrawn. Computed for every method, withdrawn or not, so the settings
    #: page can warn before the write rather than after a refusal — and so the
    #: number an operator acknowledges is one they were shown.
    would_strand: int


class AccountsWithoutFactor(SanitizedBaseModel):
    """How many accounts each level would ask to set a second factor up.

    Both figures on every read, so the page states the consequence of a choice
    before it is made rather than after it binds anybody.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: Accounts above ``member`` on the platform ladder holding neither an
    #: authenticator nor a passkey.
    platform_roles: int
    #: Every live account holding neither.
    everyone: int


class PlatformAuthSettingsResponse(SanitizedBaseModel):
    """The ways in this deployment permits, with the facts a change would turn
    on."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    methods: List[LoginMethodStatus]
    #: Guilds that require a sign-in through a provider of their own.
    #: Withdrawing single sign-on is refused while any exist; lifting the
    #: requirement releases it.
    guilds_requiring_sign_in: int
    #: Whether anything this deployment permits could answer a second-factor
    #: requirement — the authenticator app or a passkey, either will do. False
    #: means the requirement below cannot be raised, and the server refuses it
    #: with ``SETTINGS_FACTOR_REQUIREMENT_NO_METHOD``. Answered here so the
    #: surface can say so before the write, and so it never has to work out
    #: which methods count.
    factor_methods_permitted: bool = True
    #: How long somebody may stay signed in before signing in again, in hours.
    #: ``None`` asks for no limit, which is the default. A community held to
    #: the compliance standard overrides it downwards for its own members.
    session_max_hours: Optional[int] = None
    #: How long a session may be left alone before it lapses, in minutes.
    #: ``None`` leaves the deployment's configured refresh window. A community
    #: held to the compliance standard narrows it further for its members.
    session_idle_minutes: Optional[int] = None
    #: Who this deployment asks to hold a second factor.
    second_factor_requirement: SecondFactorRequirement = SecondFactorRequirement.nobody
    #: What each level would ask for, as things stand.
    accounts_without_factor: AccountsWithoutFactor


class SessionLifetimeUpdate(SanitizedBaseModel):
    """The absolute limit on staying signed in, in hours.

    ``None`` asks for no limit. It has to be longer than the idle window to
    mean anything: set shorter, it is the only thing ending a session and the
    idle window stops mattering — which is a fair thing to ask for, and the
    reason the field is free rather than a list of blessed figures.
    """

    session_max_hours: Optional[int] = Field(default=None, ge=1, le=87600)
    #: The idle window, in minutes. ``None`` asks for no limit of its own and
    #: leaves ``AUTH_REFRESH_TTL_DAYS``. Floored at a minute — anything less
    #: ends a session while somebody is still reading the page.
    session_idle_minutes: Optional[int] = Field(default=None, ge=1, le=525600)


class SecondFactorRequirementUpdate(SanitizedBaseModel):
    """Who to ask for a second factor from now on.

    Nobody is signed out by the change. An account the level covers is asked
    at its next request and answers it where it stands; one that cannot
    present a factor — the app on a phone, a personal API key — works again
    once its owner holds one.
    """

    level: SecondFactorRequirement


class LoginMethodsUpdate(SanitizedBaseModel):
    """The methods to permit from now on. Order and repetition are ignored."""

    methods: List[LoginMethod] = Field(min_length=1)
    #: Set to proceed with a change that strands accounts. It must equal the
    #: number the server currently computes, so it cannot be sent blind or
    #: replayed once the number has moved — an operator acknowledges a figure
    #: they were actually shown.
    acknowledge_stranded: Optional[int] = Field(default=None, ge=0)


class InterfaceSettingsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    light_accent_color: str
    dark_accent_color: str


class InterfaceSettingsUpdate(SanitizedBaseModel):
    light_accent_color: str
    dark_accent_color: str


class CommunitySettingsResponse(SanitizedBaseModel):
    """Whether this deployment runs a community directory.

    Read back by the owner's settings page after a write; everyone else learns
    the same fact from ``GET /config``, which is where the SPA reads it to
    decide whether to offer the directory at all.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    community_directory_enabled: bool
    age_gate_enabled: bool
    #: The policy a newly created account starts on. Read once, when the
    #: account is made; changing it moves no existing account.
    default_dm_policy: DmPolicy
    #: Whether this deployment offers direct messages at all. Also on
    #: ``GET /config``, which is where every signed-in page reads it.
    direct_messages_enabled: bool
    #: How long a deleted community is kept before it is destroyed, in days.
    #: ``None`` means it is never destroyed — a deployment that has undertaken
    #: to keep what its members put in it. Owner-only, deployment-wide; a
    #: community has no say in its own.
    deleted_community_retention_days: Optional[int] = None
    #: How long a deleted account is kept before it is erased, in days. Its own
    #: figure rather than the one above: what a deployment owes the people in a
    #: community and what it owes the person leaving are different questions.
    #: ``None`` means never, for a deployment required to keep accounts.
    deleted_account_retention_days: Optional[int] = None


class CommunitySettingsUpdate(SanitizedBaseModel):
    community_directory_enabled: bool
    #: Whether an account must confirm it is 16 or older to join a listed
    #: guild from the directory. Omitted leaves it as it was — the two switches
    #: are separate decisions and the directory one is written far more often.
    age_gate_enabled: Optional[bool] = None
    #: Omitted leaves it as it was, like the switch above.
    default_dm_policy: Optional[DmPolicy] = None
    #: Whether this deployment offers direct messages at all. Omitted leaves it
    #: as it was; it is independent of the directory, which a deployment can
    #: run with or without messaging.
    direct_messages_enabled: Optional[bool] = None
    #: How long a deleted community is kept, in days. This one reads its
    #: presence rather than its value, because ``null`` is an answer here
    #: ("never destroy one") and not the absence of one: omit the field to
    #: leave the window alone, send a number to set it, send ``null`` to turn
    #: destruction off. The endpoint inspects ``model_fields_set``.
    deleted_community_retention_days: Optional[int] = Field(
        default=None,
        ge=MIN_GUILD_RETENTION_DAYS,
        le=MAX_GUILD_RETENTION_DAYS,
    )
    #: The account window, read the same way: omit to leave it alone, send a
    #: number to set it, send ``null`` to stop erasing on a timer.
    deleted_account_retention_days: Optional[int] = Field(
        default=None,
        ge=MIN_GUILD_RETENTION_DAYS,
        le=MAX_GUILD_RETENTION_DAYS,
    )


class EmailSettingsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    host: Optional[str] = None
    port: Optional[int] = None
    secure: bool = False
    reject_unauthorized: bool = True
    username: Optional[str] = None
    has_password: bool = False
    from_address: Optional[str] = None
    test_recipient: Optional[EmailStr] = None


class EmailSettingsUpdate(SanitizedBaseModel):
    host: Optional[str] = None
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    secure: bool = False
    reject_unauthorized: bool = True
    username: Optional[str] = None
    password: Optional[RawTextStr] = None
    from_address: Optional[str] = None
    test_recipient: Optional[EmailStr] = None


class EmailTestRequest(SanitizedBaseModel):
    recipient: Optional[EmailStr] = None


class EmailTestResponse(SanitizedBaseModel):
    """Result of a test-email send. ``status`` is ``"sent"`` on success;
    failures surface as HTTP errors, not a status value here."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    status: str


# --- Object storage schemas ---


class StorageSettingsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    backend: Literal["local", "s3"] = "local"
    s3_bucket: Optional[str] = None
    s3_region: str = "us-east-1"
    s3_endpoint_url: Optional[str] = None
    s3_access_key_id: Optional[str] = None
    has_secret_access_key: bool = False
    s3_use_path_style: bool = False
    s3_kms_key_id: Optional[str] = None
    s3_local_fallback: bool = False


class StorageSettingsUpdate(SanitizedBaseModel):
    backend: Literal["local", "s3"] = "local"
    s3_bucket: Optional[str] = None
    s3_region: str = "us-east-1"
    s3_endpoint_url: Optional[str] = None
    s3_access_key_id: Optional[str] = None
    s3_secret_access_key: Optional[RawTextStr] = None
    s3_use_path_style: bool = False
    s3_kms_key_id: Optional[str] = None
    s3_local_fallback: bool = False


class StorageTestResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    success: bool
    message: str


class StorageBackfillStatusResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    status: Literal["idle", "running", "complete", "failed"] = "idle"
    copied: int = 0
    skipped: int = 0
    failed: int = 0
    hash_mismatches: int = 0
    failed_keys: List[str] = Field(default_factory=list)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None


# --- OIDC Claim Mapping schemas ---


class OIDCClaimMappingCreate(SanitizedBaseModel):
    #: Whose claim this rule reads. Required: a claim value means nothing
    #: until you know which provider asserted it.
    provider_id: int
    claim_value: str = Field(min_length=1, max_length=500)
    target_type: str  # "guild" or "initiative"
    guild_id: int
    guild_role: str = "member"
    initiative_id: Optional[int] = None
    initiative_role_id: Optional[int] = None


class OIDCClaimMappingUpdate(SanitizedBaseModel):
    provider_id: Optional[int] = None
    claim_value: Optional[str] = Field(default=None, min_length=1, max_length=500)
    target_type: Optional[str] = None
    guild_id: Optional[int] = None
    guild_role: Optional[str] = None
    initiative_id: Optional[int] = None
    initiative_role_id: Optional[int] = None


class OIDCClaimMappingRead(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    provider_id: int
    claim_value: str
    target_type: str
    guild_id: int
    guild_role: str
    initiative_id: Optional[int] = None
    initiative_role_id: Optional[int] = None
    provider_name: Optional[str] = None
    guild_name: Optional[str] = None
    initiative_name: Optional[str] = None
    initiative_role_name: Optional[str] = None


class OIDCMappingsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    claim_path: Optional[str] = None
    mappings: List[OIDCClaimMappingRead] = Field(default_factory=list)


# The mapping form needs every guild, initiative, and initiative role to
# populate its target selectors. Ids collide across guild schemas, so
# initiatives and roles carry their ``guild_id`` for the client to disambiguate.
class OIDCMappingOptionGuild(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    name: str


class OIDCMappingOptionInitiative(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    name: str
    guild_id: int


class OIDCMappingOptionRole(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    name: str
    initiative_id: int
    guild_id: int


class OIDCMappingOptionsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    guilds: List[OIDCMappingOptionGuild] = Field(default_factory=list)
    initiatives: List[OIDCMappingOptionInitiative] = Field(default_factory=list)
    initiative_roles: List[OIDCMappingOptionRole] = Field(default_factory=list)
