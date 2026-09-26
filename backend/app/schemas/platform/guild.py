from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import field_validator, ConfigDict, EmailStr, Field

from app.core.guild_auth_options import GuildAuthOption
from app.core.messages import GuildMessages
from app.schemas.base import RawTextStr, RichTextStr, SanitizedBaseModel, TitleStr

from app.core.email_masking import mask_email
from app.models.platform.guild import (
    DEFAULT_BANNER,
    BannerFade,
    BannerTextAlign,
    GuildCategory,
    GuildRole,
    GuildStatus,
)


class GuildBannerRead(SanitizedBaseModel):
    """A guild's banner, whole — the picture and the look around it.

    ``image_url`` is where to fetch the artwork, never the bytes: a banner is
    ~350 KB and this rides in payloads that list every guild the caller is in.
    Which rendition it names is the surface's business — a guild's own front
    page gets the full one, a directory card the card one. ``None`` means no
    artwork, not no banner: the fill is what shows then.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    image_url: Optional[str] = None
    color: str = DEFAULT_BANNER["color"]
    text_color: str = DEFAULT_BANNER["text_color"]
    text_align: BannerTextAlign = BannerTextAlign(DEFAULT_BANNER["text_align"])
    fade: BannerFade = BannerFade(DEFAULT_BANNER["fade"])


class GuildBannerWrite(SanitizedBaseModel):
    """The banner a guild admin sets, whole.

    Every field is required: the banner is one value and this replaces it, so a
    body naming two of the four would have to mean "leave the rest" — a merge
    the caller cannot see the result of. Sending ``null`` for the whole object
    is how you go back to the default. The artwork is set through its own
    endpoint; it is bytes, not a look.

    The layout fields are typed as their enums, so anything outside the
    vocabulary is a 422 rather than a rule the service restates; the colours
    are text here and normalized in the service.
    """

    color: RawTextStr
    text_color: RawTextStr
    text_align: BannerTextAlign
    fade: BannerFade


class GuildBase(SanitizedBaseModel):
    name: str
    description: Optional[RichTextStr] = None


class GuildCreate(GuildBase):
    name: TitleStr
    #: Make another account the guild's admin instead of the caller.
    #:
    #: Honoured only for a caller holding ``guilds.manage``; anyone else
    #: sending it is refused rather than quietly ignored, so a request that
    #: names an owner never succeeds under a different one. The account must
    #: already exist — this never creates one.
    owner_user_id: Optional[int] = Field(default=None, ge=1)


class GuildCan(SanitizedBaseModel):
    """What the caller may do in a community, as the server answers it.

    Each flag is the check the routes that do the thing run, so a client reads
    its affordances here rather than working them out from a rung."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: Open it at all. False for a community in time out, which its
    #: administrators still see listed; the flags below say what the rung
    #: carries once it is lifted.
    enter: bool = False
    #: Reach its work. A settings grant reaches the configuration alone.
    content: bool = False
    #: Run its configuration, roster and invites: its administrator, or a
    #: settings grant at either rung.
    administer: bool = False
    #: Change that configuration: its administrator, or a settings grant
    #: beside a ``read_write`` content grant.
    configure: bool = False
    #: Administer its work — create and delete initiatives, add the
    #: community's own calendars. The membership row's administrator; no
    #: grant makes one.
    administer_content: bool = False
    #: Hold its top seat: sign-in, billing, AI, apps, data and deletion.
    seat: bool = False


class GuildRead(GuildBase):
    """A guild as its own members see it (``GET /communities/`` and friends).

    The payload has two tiers, decided in one place — ``_serialize_guild`` in
    the guilds router:

    - The fields below with no note are for **every member**: guild identity,
      the caller's own rung, the roster size, ``content_read_only``.
    - The ones marked ADMIN-ONLY are guild administration — caps, plan label,
      retention window, lifecycle status, sign-in entitlement. They back
      admin-gated surfaces, so a regular member's payload leaves them ``None``.
      (Operators read the same underlying columns through
      :class:`PlatformGuildStorageRead` instead, which is capability-gated.)
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    #: The rung this caller holds in the community: the membership row's own,
    #: or the one a live settings grant confers for its window. Shown as it
    #: stands; what it lets them do is ``can``.
    role: GuildRole
    can: GuildCan = Field(default_factory=GuildCan)
    position: int
    created_at: datetime
    updated_at: datetime
    # ADMIN-ONLY. Trash retention window, set from the guild's trash settings tab.
    retention_days: Optional[int] = None
    # ADMIN-ONLY. Operator-set caps, rendered against usage on the settings page
    # (the usage half, /c/{id}/storage/usage, is guild-admin only too).
    max_storage_bytes: Optional[int] = None
    max_users: Optional[int] = None
    member_count: int = 0
    # ADMIN-ONLY. Display/audit label of the paid tier (NULL = none /
    # self-hosted). Shown by the plan panel only when a billing portal is
    # configured; it is DISPLAY metadata and is never read in an enforcement
    # path (billing_foss_test scans for that). Enforcement reads
    # max_storage_bytes / max_users / status.
    tier_name: Optional[str] = None
    # ADMIN-ONLY. Lifecycle status, so the app can show an admin a suspended
    # community as closed and a read-only one with its notice. ``None`` for
    # non-admin members — the moderation hold is never disclosed to them
    # (suspended guilds are also filtered from their guild list entirely).
    status: Optional[GuildStatus] = None
    # True when content writes are frozen (read_only lifecycle status). Unlike
    # ``status`` this IS serialized to every member: writes fail at the
    # database role level regardless, so the UI must be able to drop its write
    # affordances — the flag discloses the effect, not the reason.
    content_read_only: bool = False
    # ADMIN-ONLY, and only for a suspended guild: who the closed entry tells
    # them to contact — the deployment's moderation contact, else its general
    # one (``app.services.platform.intake.contact_for``). ``None`` when neither
    # is set, or for any other guild.
    contact_email: Optional[str] = None
    # ADMIN-ONLY. What this guild may do about its own sign-in (operator
    # entitlement), so their settings UI knows which surfaces to offer;
    # ``None`` for non-admin members (they never configure auth).
    auth_options: Optional[List[GuildAuthOption]] = None
    # ADMIN-ONLY. Whether a personal API key may be used against this guild.
    # ``None`` for non-admin members: it is read by the settings surface that
    # sets it, and nothing a member does depends on the answer.
    allow_api_keys: Optional[bool] = None
    # ADMIN-ONLY. Whether this guild holds its members to the twelve-hour
    # session standard. ``None`` for non-admin members, like the one above:
    # the settings surface that sets it is what reads it.
    enforce_compliance_session: Optional[bool] = None
    # ADMIN-ONLY. Whether reaching this guild asks for a second factor.
    # ``None`` for non-admin members, like the two above.
    require_second_factor: Optional[bool] = None
    # Community directory opt-in and its subject tags. Guild identity, not
    # administration: every member sees them (they are published to strangers
    # anyway), and the settings page shows the controls to admins.
    is_community: bool = False
    categories: List[GuildCategory] = []
    # Whether this guild renders members' real names. Off — the default —
    # means it renders handles. A listed guild is always off and cannot be
    # switched on.
    show_member_names: bool = True
    # The 18+ declaration. ``None`` — unanswered — is the normal state for a
    # guild that has never been listed; listing requires an explicit ``False``.
    has_adult_content: Optional[bool] = None
    # The guild's banner, at full size. Never absent — every guild has one, so
    # nothing downstream renders a guild that has none.
    banner: GuildBannerRead = GuildBannerRead()
    # How many of this guild's members have it open right now. A live reading
    # taken from the process answering the request rather than a stored
    # column — the same figure the directory card shows, and the same caveat: a
    # sense of how busy the guild is, not a number to reconcile against
    # anything. Zero is also what a request served by a process holding none of
    # the guild's sockets answers.
    online_count: int = 0
    # Where to fetch the guild's icon, or ``None`` when it has none. A URL like
    # the banner's: this payload lists every guild the caller is in, and the
    # icon used to be a data URI inlined into all of them.
    icon_url: Optional[str] = None


class GuildPaymentIssueRead(SanitizedBaseModel):
    payment_failed: bool = False


class GuildInviteCreate(SanitizedBaseModel):
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = Field(default=1, ge=1)
    invitee_email: Optional[EmailStr] = None


class GuildInviteRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    code: str
    guild_id: int
    created_by: Optional[int]
    expires_at: Optional[datetime]
    max_uses: Optional[int]
    uses: int
    # Masked (``j***n@e***m``). Whoever typed the address already has it,
    # and a guild's other admins never did — the invite still matches the whole
    # address on redemption, from the ciphertext.
    invitee_email: Optional[str]
    created_at: datetime

    @field_validator("invitee_email", mode="after")
    @classmethod
    def _mask_invitee_email(cls, value: Optional[str]) -> Optional[str]:
        return mask_email(value)


class GuildInviteAcceptRequest(SanitizedBaseModel):
    code: str


class GuildInviteStatus(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    code: str
    guild_id: Optional[int] = None
    guild_name: Optional[str] = None
    is_valid: bool
    reason: Optional[str] = None
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = None
    uses: Optional[int] = None


class GuildUpdate(SanitizedBaseModel):
    name: Optional[TitleStr] = None
    description: Optional[RichTextStr] = None
    # Trash retention period in days. None means "never auto-purge".
    # Sentinel "unset" semantics: explicitly omit the field to leave the
    # current setting untouched; set null to switch to never-purge.
    retention_days: Optional[int] = Field(default=None, ge=1, le=3650)
    # Community directory opt-in and subject tags. Omit-to-skip, like the
    # fields above: the endpoint inspects ``model_fields_set``, so a PATCH that
    # only renames a guild never disturbs its listing. A null ``categories``
    # is read as "no categories" — the empty list means the same thing and the
    # UI sends that — while a null ``is_community`` is a no-op (a boolean
    # opt-in has no third state).
    is_community: Optional[bool] = None
    categories: Optional[List[GuildCategory]] = None
    # Whether to render members' real names instead of their handles. Listing
    # the guild turns it off in the same write and the endpoint refuses to set
    # both, which ck_guilds_community_member_names also enforces.
    show_member_names: Optional[bool] = None
    # The whole banner, replaced. Omit-to-skip like the fields above; an
    # explicit null puts it back to the default rather than clearing it, since
    # a banner is never colourless and never without a layout.
    banner: Optional[GuildBannerWrite] = None
    # The 18+ declaration, and the one field here where null is an ANSWER
    # rather than a skip — it puts the guild back to undeclared. Omitting the
    # field is how you leave it alone, so this is read from
    # ``model_fields_set`` rather than from the value being non-null.
    has_adult_content: Optional[bool] = None
    # NOTE: deliberately no cap/status/tier fields here. Those are
    # operator/billing enforcement inputs (the platform Guilds tab or the
    # verified billing path) — a guild's own admins must never set them, and
    # the column-scoped UPDATE grant on public.guilds (migration 0138) makes
    # the database enforce that even if a field regressed into this schema.


class PlatformGuildStorageRead(SanitizedBaseModel):
    """Operator view of a guild's storage cap (platform settings → Guilds tab).

    Unlike :class:`GuildRead`, this carries no per-user membership fields
    (``role``/``position``): the platform operator lists every guild regardless
    of whether they belong to it, so only platform-wide attributes apply.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    member_count: int = 0
    # Plan label exactly as the billing service last set it — display/audit
    # metadata, never an enforcement input (the caps below are what enforce).
    # Echoed verbatim; this app neither invents nor interprets a plan name, and
    # None means no billing service has named one for this guild.
    tier_name: Optional[str] = None
    # Max total stored blob bytes for this guild. None means "unlimited".
    max_storage_bytes: Optional[int] = None
    # Max number of members for this guild. None means "unlimited".
    max_users: Optional[int] = None
    # Lifecycle status (active / read_only / suspended / deleted). Surfaced
    # only to platform operators here — never to guild members (GuildRead omits it).
    status: GuildStatus = GuildStatus.active
    status_changed_at: Optional[datetime] = None
    # The statuses the operator may move this guild to, the current one
    # included where it is one of them (``operator_status_choices``). Empty
    # for a deleted guild.
    status_choices: List[GuildStatus] = Field(default_factory=list)
    # When a deleted guild is destroyed: its deletion time plus the retention
    # window. Null unless ``status`` is ``deleted``. Computed from the two
    # columns beside it rather than stored, so the window is stated in one
    # place (``guild_purge.GUILD_RETENTION_DAYS``).
    purge_at: Optional[datetime] = None
    # Whether anybody left in the guild can still run it — a ``superadmin``
    # seat. False after a deletion that cleared the roster, which is what makes
    # a restore ask the operator to seat somebody.
    has_seat: bool = True
    # Per-guild sign-in entitlements, set from the platform Guilds dashboard.
    auth_options: List[GuildAuthOption] = Field(default_factory=list)
    # Whether this guild may upload banner artwork (operator toggle). On by
    # default; a guild without it picks a banner colour instead.
    banner_image_enabled: bool = True
    # Whether this guild's members may send a help request (operator toggle).
    # Off by default: the deployment that receives them is the one that decides
    # it is staffing them.
    support_enabled: bool = False


class PlatformGuildRestore(SanitizedBaseModel):
    """Bring a deleted guild back (platform ``guilds.manage``).

    ``status`` is what it returns at — the operator decides, because a
    community suspended for nonpayment and then deleted should not come back
    trading, and a column remembering what it used to be would be one more
    thing to keep correct for a decision somebody is making anyway.

    ``seat_user_id`` names the account that will run it, and is required only
    when the guild's roster no longer holds a ``superadmin`` — which is what a
    deletion that cleared the roster leaves behind. The endpoint re-checks
    that rather than trusting the client's reading of it.
    """

    status: GuildStatus = GuildStatus.active
    seat_user_id: Optional[int] = Field(default=None, ge=1)

    @field_validator("status")
    @classmethod
    def _not_deleted(cls, value: GuildStatus) -> GuildStatus:
        if value == GuildStatus.deleted:
            raise ValueError(GuildMessages.GUILD_RESTORE_STATUS_INVALID)
        return value


class PlatformGuildStorageUpdate(SanitizedBaseModel):
    """Set a guild's storage caps and/or lifecycle status from the Guilds tab.

    The cap fields use omit-to-skip sentinel semantics (the endpoint inspects
    ``model_fields_set``): omit a field to leave it untouched, send ``null`` to
    reset that cap to unlimited, or send a number to set it. ``status`` is
    omit-to-skip too (a lifecycle status is never null), validated against
    :class:`GuildStatus`. A PATCH may carry any subset.
    """

    max_storage_bytes: Optional[int] = Field(default=None, ge=0)
    max_users: Optional[int] = Field(default=None, ge=1)
    status: Optional[GuildStatus] = None

    @field_validator("status")
    @classmethod
    def _status_is_settable(cls, value: GuildStatus | None) -> GuildStatus | None:
        """``deleted`` is not an operator setting.

        It is reached by deleting a guild and left by restoring one, both of
        which do a good deal more than move this column: clearing the guild's
        app grants as it goes, seating somebody who can run it as it returns.
        Those two endpoints own the transition; this field does not.
        """
        if value == GuildStatus.deleted:
            raise ValueError(GuildMessages.GUILD_STATUS_NOT_SETTABLE)
        return value

    # Per-guild sign-in entitlements. Omit-to-skip; a sent list replaces the
    # set outright, and an empty one grants nothing.
    auth_options: Optional[List[GuildAuthOption]] = None
    # Banner-artwork entitlement. Omit-to-skip, same as the one above.
    banner_image_enabled: Optional[bool] = None
    # Help-request entitlement. Omit-to-skip, same as the one above.
    support_enabled: Optional[bool] = None


#: What a community may require, beyond naming one provider. ``sso`` means its
#: own single sign-on, whichever of its providers serves it — the deployment's
#: providers are not its own. ``totp`` means the session carried the account's
#: second factor; ``passkey`` that it was opened, or stepped up, with one. The
#: platform's ``login_method`` vocabulary minus ``password`` and ``email_otp``,
#: which only the deployment decides about: a community's rule is about what a
#: session has proved, and those two are about whether the deployment offers
#: them at all. The same asymmetry the database holds as CHECKs on
#: ``require_methods``.
GuildRequirableMethod = Literal["sso", "totp", "passkey"]


class GuildAuthPolicyRead(SanitizedBaseModel):
    """The guild's sign-in requirement. ``open`` is the default (no stored
    row). ``required`` names a provider a session must have satisfied, asks for
    the guild's own single sign-on without naming which provider serves it, or
    both."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    policy: Literal["open", "required"]
    provider_id: Optional[int] = None
    provider_slug: Optional[str] = None
    provider_display_name: Optional[str] = None
    require_methods: list[GuildRequirableMethod] = Field(default_factory=list)
    #: Whether the deployment already asks every account for a second factor.
    #: The community's own box for it is not offered while this is true —
    #: there is nothing left for it to add — and a rule already written stays
    #: on the row, in force again if the deployment lowers its answer.
    factor_required_by_platform: bool = False


class GuildAuthPolicyUpdate(SanitizedBaseModel):
    policy: Literal["open", "required"]
    provider_id: Optional[int] = None
    #: ``["sso"]`` asks for the community's own single sign-on and ``["totp"]``
    #: for the account's second factor; both may be asked for at once.
    #: ``password`` is absent from the type on purpose: whether passwords exist
    #: at all is the deployment's question.
    require_methods: list[GuildRequirableMethod] = Field(default_factory=list)


class GuildAuthSettingsRead(SanitizedBaseModel):
    """The current controls on the superadmin's Authentication page."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    auth_options: List[GuildAuthOption] = Field(default_factory=list)
    allow_api_keys: bool
    enforce_compliance_session: bool
    require_second_factor: bool = False
    allow_push_notifications: bool = True
    allow_email_notifications: bool = True
    redact_notification_content: bool = False


class GuildApiAccessRead(SanitizedBaseModel):
    """Whether this guild accepts personal API keys."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    allow_api_keys: bool


class GuildSecondFactorRead(SanitizedBaseModel):
    """Whether reaching this community asks for a second factor."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    require_second_factor: bool
    #: Whether the deployment offers a second factor at all. With none, there
    #: is nothing for a community to ask for and the control is not offered.
    available: bool = True


class GuildSecondFactorUpdate(SanitizedBaseModel):
    """Ask for one, or stop. Which kinds count is the deployment's answer."""

    require_second_factor: bool


class GuildApiAccessUpdate(SanitizedBaseModel):
    """Set it. ``false`` means no key can be minted into this guild and no
    request carrying one reaches it; keys already minted stop working here."""

    allow_api_keys: bool


class GuildSessionLimitRead(SanitizedBaseModel):
    """Whether this guild holds its members to the twelve-hour session
    standard."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    enforce_compliance_session: bool


class GuildSessionLimitUpdate(SanitizedBaseModel):
    """Set it. ``true`` means this guild's members sign in again every twelve
    hours, whatever the deployment's own limit says."""

    enforce_compliance_session: bool


class GuildNotificationPolicyRead(SanitizedBaseModel):
    """What this community's notifications may leave the app carrying."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    allow_push_notifications: bool
    allow_email_notifications: bool
    redact_notification_content: bool
    #: What the deployment already asks of every community, so the page can say
    #: that a switch has nothing to add rather than offering the same answer
    #: twice. The stricter of the two applies, so a deployment that has already
    #: declined a channel leaves nothing here to decline.
    push_allowed_by_platform: bool = True
    email_allowed_by_platform: bool = True
    redacted_by_platform: bool = False


class GuildNotificationPolicyUpdate(SanitizedBaseModel):
    """Set them. Each one restricts this community's notifications and nothing
    else: no switch here relaxes what the deployment has already said."""

    allow_push_notifications: bool
    allow_email_notifications: bool
    redact_notification_content: bool


class GuildDeletionRequest(SanitizedBaseModel):
    """Body for ``DELETE /communities/{id}``.

    Deleting a guild cascades through every initiative, project, task,
    document, membership, invite, and settings row it owns, so the
    endpoint gates on two confirmations:

    - ``confirmation_text`` must equal ``DELETE COMMUNITY <NAME>`` (the whole
      phrase uppercased) so the action can't be triggered by a stray click.
    - ``password`` is the current user's password. An account that holds
      none — one that signs in with a passkey or through an identity
      provider — has nothing to confirm with and answers with the phrase
      alone, mirroring the account-deletion endpoint, which is why it
      defaults to empty.
    """

    password: RawTextStr = ""
    confirmation_text: str


class GuildOrderUpdate(SanitizedBaseModel):
    model_config = ConfigDict(populate_by_name=True)
    guild_ids: list[int] = Field(min_length=1, alias="guildIds")


class GuildEntitlementsRead(SanitizedBaseModel):
    """What an operator has turned on for one guild, for its own admins.

    Deliberately its own read rather than fields on :class:`GuildRead`: these
    are the operator's decisions about a guild, they live on the separate
    ``guild_administration`` row, and only a guild admin has any use for them —
    a member's guild payload should not be carrying them at all.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    guild_id: int
    # Whether this guild may upload banner artwork. Off means the settings page
    # offers the banner colour alone; a banner already uploaded keeps showing.
    banner_image_enabled: bool = True


class GuildMembershipUpdate(SanitizedBaseModel):
    """Schema for updating a user's guild membership role."""

    role: GuildRole


class LeaveGuildEligibilityResponse(SanitizedBaseModel):
    """Response for checking if a user can leave a guild.

    Two things stop them, and the caller is told which. Being the guild's last
    admin is one. Holding its only superadmin seat while the guild requires
    a sign-in is the other — the requirement is lifted from the surface that
    seat holds, so the seat stays for as long as the requirement does.

    Content they own is released on the way out and left unowned for a guild
    admin to claim, so there is nothing to hand over first.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    can_leave: bool
    is_last_superadmin: bool = False


class CommunityGuildRead(SanitizedBaseModel):
    """One card in the community directory.

    Deliberately not a :class:`GuildRead`: the reader is a stranger, so this
    carries only what the guild published by opting in — its identity, its
    shelves, and how many people are already there. No membership fields (they
    have none), no lifecycle status, no administration. ``already_member`` is
    about the *caller*, and only says whether the Join button applies to them.

    ``online_count`` is how many of those people have the guild open right now.
    It is a live reading rather than a stored one, taken from the process
    answering the request, so it is a sense of how busy a guild is rather than a
    figure to reconcile against anything.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    name: str
    description: Optional[RichTextStr] = None
    icon_url: Optional[str] = None
    categories: List[GuildCategory] = []
    member_count: int = 0
    online_count: int = 0
    already_member: bool = False
    # The guild's banner, its ``image_url`` naming the card rendition rather
    # than the full one: a directory page is up to sixty of these, so the bytes
    # stay out of the payload and are fetched (and then cached) per card. The
    # rest of it needs no fetch at all.
    banner: GuildBannerRead = GuildBannerRead()


class CommunityGuildPage(SanitizedBaseModel):
    """A page of directory results, plus how many matched in total."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[CommunityGuildRead]
    total: int
