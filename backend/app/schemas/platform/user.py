from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import (
    ConfigDict,
    EmailStr,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.schemas.base import RawTextStr, SanitizedBaseModel, TitleStr

from app.core.capabilities import Capability, capabilities_for
from app.core.emoji import validate_emoji
from app.core.profile_decorations import (
    DATED_DECORATIONS,
    MAX_FRAME_TINTS,
    MIN_GRAD_YEAR,
    TINTABLE_FRAMES,
    TROPHY,
    BANNER,
    FRAME,
    max_grad_year,
    validate_decoration_id,
    validate_tint,
)
from app.core.role_context import guild_shows_member_names
from app.models.platform.user import Presence, UserRole, UserStatus
from app.core.config import settings

# ``avatar_url`` is where a user's picture is: either a path this API serves
# (``/api/v1/users/{id}/avatar/{sha256}`` — the bytes live in ``user_avatars``
# and are uploaded through ``PUT /users/me/avatar``) or a URL somewhere else,
# from an OIDC ``picture`` claim. The two are alternatives, and one field holds
# whichever applies.
#
# There is deliberately no schema by which one account edits another's profile.
# A guild admin manages *membership* — who is in the guild — not the person's
# record, which spans every guild they belong to.
#
# Two identity rules are enforced here rather than per endpoint, so the shapes
# themselves are the proof:
#
# * An address never reaches a guild. ``email`` is absent from every
#   guild-scoped shape — roster, picker and member management alike — and kept
#   only on ``UserRead`` (your own account) and the platform admin reads.
# * A real name is shown only where a guild has asked for it.
#   ``GuildNameVisibility`` drops ``full_name`` unless the request's guild has
#   ``show_member_names`` set, which a community-listed guild cannot.
#
# What is always present is the handle: ``username`` plus ``discriminator``,
# rendered ``foobar#1234`` with the number muted. They are two fields rather
# than one string because the client styles them differently.


class GuildNameVisibility(SanitizedBaseModel):
    """Drops ``full_name`` unless the request's guild renders real names.

    One validator rather than a branch at each serializer: the flag is set with
    the guild context (``app.core.role_context``), so nothing that builds one of
    these shapes has to remember. A request outside any guild renders handles
    too, which is the same default.
    """

    @model_validator(mode="after")
    def _apply_guild_name_visibility(self):
        if not guild_shows_member_names():
            object.__setattr__(self, "full_name", None)
        return self


class UserBase(SanitizedBaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    role: UserRole = UserRole.member


class UserCreate(SanitizedBaseModel):
    # Deliberately does NOT inherit ``UserBase.role``. Platform role must
    # never be settable from a create payload: this schema backs both
    # self-registration (``/auth/register``) and guild-admin user creation
    # (``POST /users/``), and neither caller is authorized to grant a
    # platform role from the request body. Registration computes the role
    # itself (first user = owner, everyone else = member) and the admin
    # endpoint forces ``member``; standing platform roles change only via
    # ``/admin/users/{id}/platform-role`` (capability-gated, bounded
    # delegation). See SEC-1.
    email: EmailStr
    # The name part of the handle. The number behind it is drawn server-side —
    # it is never anyone's to choose.
    username: str = Field(max_length=64)
    full_name: Optional[TitleStr] = None
    # ``max_length`` is a cheap DoS gate so we don't argon2-hash a
    # multi-megabyte payload. The min length and breach checks live in
    # ``app.core.password_policy`` and are invoked from the endpoint,
    # so all policy failures surface with a flat error code from
    # ``PasswordMessages`` that ``errors.json`` can map.
    password: RawTextStr = Field(max_length=256)
    # Optional IANA timezone forwarded by the SPA on registration so a
    # new account starts at the user's wall clock instead of the model
    # default ``"UTC"``. Validated server-side by ``_normalize_timezone``;
    # omitted by non-SPA callers, in which case the model default applies.
    timezone: Optional[str] = None
    # Optional captcha token supplied by the SPA's widget when the
    # deployment has ``CAPTCHA_PROVIDER`` configured. Verified
    # server-side via ``app.services.captcha`` before the row is
    # written. Ignored when captcha isn't configured.
    captcha_token: Optional[str] = None


class UserPublic(GuildNameVisibility):
    """A person, as everyone else sees them.

    The handle (``username`` + ``discriminator``) is always here and is what
    renders when there is no name to show. ``status`` comes along so the
    frontend can mark an account that is no longer in use without replacing the
    identifier that keeps an old thread legible.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    username: str
    discriminator: int
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status: UserStatus = UserStatus.active


class UserGuildMember(UserPublic):
    """A member, for the guild's own member-management surface.

    Carries the membership facts a guild admin manages — guild role, whether
    the membership is OIDC-managed, when the account joined — and none of the
    account's own: no address, no platform tier, no word on whether the address
    was ever confirmed, and a name only where the guild shows names. Two
    members are told apart by their handle, which is unique.
    """

    guild_role: Optional[str] = None  # Guild role (admin/member) - set by endpoint
    oidc_managed: bool = False  # Whether membership is managed via OIDC claim mappings
    status: UserStatus
    created_at: datetime
    initiative_roles: List["UserInitiativeRole"] = Field(default_factory=list)


class UserSummary(GuildNameVisibility):
    """Slim user projection for typeahead and picker surfaces.

    What it keeps is what it takes to *draw* a person and say where they stand
    in the guild being read: the handle, the avatar, what they have put around
    it, and their guild role. A decoration is an id naming a catalog entry and
    a role is one word, so all of it is short, and none of it costs a query
    beyond the one already being run.

    What it drops is the account's own business and anything that would cost
    another round trip: no address, no platform tier, no ``initiative_roles``
    (an N+1 enrichment on the full roster), no timestamps. The payload is
    bounded by pagination on the endpoints that serve it.

    ``profile_decorations`` is quoted and the model rebuilt below, because the
    catalog shape it names is declared further down this file.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    username: str
    discriminator: int
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status: UserStatus = UserStatus.active
    profile_decorations: Optional["ProfileDecorations"] = None
    #: ``admin`` or ``member`` in the guild this was read under. Absent where
    #: the caller asked outside a guild, which is why it is optional rather
    #: than defaulted to the quieter of the two.
    guild_role: Optional[str] = None


class UserSummaryListResponse(SanitizedBaseModel):
    """Paginated envelope for the slim user search/typeahead endpoints."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[UserSummary]
    total_count: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool


#: How long the line beside the emoji may run. Short on purpose: the bubble is
#: read in a sidebar column and over a picture, so a status is a line, not a
#: paragraph. Mirrored by the CHECK constraint in migration 20260902_0212 and
#: by ``STATUS_MAX_LENGTH`` in ``frontend/src/components/user/ProfileStatus``.
STATUS_TEXT_MAX_LENGTH = 40


class CustomStatus(SanitizedBaseModel):
    """What a person is up to, in their own words.

    One object, stored in one column, because it is one thing a person sets
    and one thing every surface that names them renders: splitting it in two
    would mean two reads and two writes for a single line of text.

    Not to be confused with ``UserStatus`` (``users.status``), which is the
    account's standing — suspended, deactivated — and is not the person's to
    write.
    """

    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    emoji: Optional[str] = None
    text: Optional[str] = Field(default=None, max_length=STATUS_TEXT_MAX_LENGTH)

    @field_validator("emoji")
    @classmethod
    def _check_emoji(cls, value: Optional[str]) -> Optional[str]:
        """Hold the status emoji to the same shape a reaction's is held to.

        An empty string means "take it off", which is how a picker sends a
        cleared selection.
        """
        if value is None or not value.strip():
            return None
        return validate_emoji(value)

    @field_validator("text")
    @classmethod
    def _blank_is_none(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else (value.strip() or None)


#: How many trophies one profile may wear. A rendering bound — a row of them
#: under a banner, not a wall.
MAX_PROFILE_TROPHIES = 6


class ProfileDecorations(SanitizedBaseModel):
    """How a profile is dressed: a banner, a frame, trophies under it.

    Every value is an **id naming a catalog entry**, never an image. The client
    resolves an id to artwork it already ships, so a decorated profile takes up
    none of a guild's upload allowance. An id this deployment's catalog doesn't
    know simply renders nothing, which is what lets a profile keep wearing
    something the store stopped offering.

    ``extra="forbid"``: the set of things a profile can wear is this list, and
    a client sending a key that isn't here is told so rather than having it
    quietly stored and never rendered.
    """

    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    banner: Optional[str] = None
    frame: Optional[str] = None
    #: The colours the wearer picked for a frame that takes them. Kept beside
    #: the frame rather than folded into its id, because the id names a catalog
    #: entry and a colour is not part of what was granted. Ignored — and
    #: dropped on write — for any frame that is not tintable.
    frame_tint: List[str] = Field(default_factory=list, max_length=MAX_FRAME_TINTS)
    trophies: List[str] = Field(default_factory=list, max_length=MAX_PROFILE_TROPHIES)
    #: The year on a decoration that carries one. Kept beside them for the same
    #: reason a tint is kept beside its frame: the id names what was granted,
    #: and the year is the wearer's. The client draws it. Ignored — and dropped
    #: on write — unless something worn takes a year.
    grad_year: Optional[int] = None

    @field_validator("banner", "frame")
    @classmethod
    def _check_single(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else validate_decoration_id(value)

    @field_validator("frame_tint")
    @classmethod
    def _check_tints(cls, value: List[str]) -> List[str]:
        return [validate_tint(colour) for colour in value]

    @model_validator(mode="after")
    def _tint_only_what_takes_it(self) -> "ProfileDecorations":
        """Keep the stored colours honest about the frame they are for.

        A colour on a frame that cannot take one would be state nothing reads
        and nothing clears — so it is dropped here, and a frame that takes one
        colour never keeps two.
        """
        takes = TINTABLE_FRAMES.get(self.frame or "", 0)
        if len(self.frame_tint) > takes:
            object.__setattr__(self, "frame_tint", self.frame_tint[:takes])
        return self

    @field_validator("grad_year")
    @classmethod
    def _check_grad_year(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        if not MIN_GRAD_YEAR <= value <= max_grad_year():
            raise ValueError(
                f"Year must be between {MIN_GRAD_YEAR} and {max_grad_year()}"
            )
        return value

    @model_validator(mode="after")
    def _year_only_what_takes_it(self) -> "ProfileDecorations":
        """Drop a year nothing worn would draw, the way a stray tint is dropped."""
        if self.grad_year is None:
            return self
        worn = {self.banner, self.frame, *self.trophies}
        if not (worn & DATED_DECORATIONS):
            object.__setattr__(self, "grad_year", None)
        return self

    @field_validator("trophies")
    @classmethod
    def _check_trophies(cls, value: List[str]) -> List[str]:
        seen: List[str] = []
        for trophy in value:
            identifier = validate_decoration_id(trophy)
            # Wearing the same one twice is a duplicate, not a second trophy.
            if identifier not in seen:
                seen.append(identifier)
        return seen

    def worn(self) -> List[tuple[str, str]]:
        """``(id, slot)`` for everything this profile is wearing.

        The one place a slot is paired with its id, so the check against a
        person's library and the shape they wrote it in cannot disagree about
        which is which.
        """
        pairs: List[tuple[str, str]] = []
        if self.banner:
            pairs.append((self.banner, BANNER))
        if self.frame:
            pairs.append((self.frame, FRAME))
        pairs.extend((trophy, TROPHY) for trophy in self.trophies)
        return pairs


# ``UserSummary`` names this shape before it is declared.
UserSummary.model_rebuild()


class OwnedDecoration(SanitizedBaseModel):
    """One decoration an account may wear, and where it came from.

    ``source`` names the marketplace pack that granted it, and is ``None`` for
    the ones that ship with the app. The client renders a picker per slot from
    these, drawing each id with the artwork it has for it and skipping the ones
    it doesn't.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    kind: str
    #: What its publisher called it. Absent for the set that ships with the
    #: app, whose names are translated in the client.
    name: Optional[str] = None
    #: The listing uid of the pack that granted it, or ``None`` for the set
    #: that ships with the app.
    source: Optional[str] = None


class DecorationPack(SanitizedBaseModel):
    """One installable set of decorations, and whether this account has it.

    A marketplace listing, so the words are the listing's — its publisher named
    it, and nobody else can. ``uid`` is the identity: it means this pack on
    every deployment carrying the catalog, and it is what a granted row records.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    uid: str
    public_id: str
    name: str
    publisher: str
    description: str
    #: Artwork for the pack itself, from the listing.
    avatar_url: Optional[str] = None
    contents: List[OwnedDecoration]
    installed: bool = False


class DecorationPackListResponse(SanitizedBaseModel):
    """Every pack this build ships. Small and read all at once — the store is
    one page."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[DecorationPack]


class OwnedDecorationsResponse(SanitizedBaseModel):
    """A person's whole library, in one read — it is small and it is all
    needed at once, because the profile form renders every slot together."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[OwnedDecoration]


class UserProfile(SanitizedBaseModel):
    """A person, as anyone can see them.

    A profile is public. It carries the handle — which is the name in this
    product, unique and never withheld — the face, the line they wrote, the
    look they picked, how they appear right now, and when they joined. It never
    carries a real name: ``full_name`` is a guild's business (a guild decides
    whether it renders names at all), and this shape has no guild in it.

    Nothing here is private to a guild, so nothing here is reached through
    one. What it does not carry is the whole point of it being its own shape:
    no address, no roles, no memberships, no preferences.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    username: str
    discriminator: int
    avatar_url: Optional[str] = None
    status: UserStatus = UserStatus.active
    custom_status: CustomStatus = Field(default_factory=CustomStatus)
    profile_decorations: ProfileDecorations = Field(default_factory=ProfileDecorations)
    #: How this person appears right now — the account, not a guild. What they
    #: picked, narrowed by whether they have anything open; set by the endpoint
    #: from the one roll that decides it.
    presence: Presence = Presence.offline
    #: When the account was made.
    joined_at: datetime


class UserRead(UserBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    username: str
    discriminator: int
    # Whether this account picked its handle. False routes the SPA to the
    # choose-your-handle screen before anything else.
    username_chosen: bool = False
    #: When this account said it belongs to somebody 13 or older, ``None``
    #: where it never has. Read by the directory's Join button, which asks
    #: before it joins rather than letting the server refuse.
    age_confirmed_at: Optional[datetime] = None
    #: When this account answered the age question as under the minimum,
    #: ``None`` where it has not. Turns the confirmation screen from a form
    #: into an explanation: the answer stands, and putting it right is
    #: somebody else's to do.
    age_below_minimum_at: Optional[datetime] = None
    #: Whether it must say so before it can carry on. True only for an account
    #: that is already in a listed guild without having confirmed — every other
    #: way in leaves the membership standing and lands here. False routes
    #: nowhere; true blocks the app on the confirmation screen, the way
    #: ``username_chosen`` false routes to the handle screen. Populated by the
    #: self endpoints (``/users/me`` and ``PATCH /users/me``), which is where
    #: the SPA reads its own account; defaults false elsewhere.
    age_confirmation_required: bool = False
    status: UserStatus
    email_verified: bool
    created_at: datetime
    updated_at: datetime
    avatar_url: Optional[str] = None
    custom_status: CustomStatus = Field(default_factory=CustomStatus)
    #: What this account picked, not what a reader would be shown: on your own
    #: record this is the setting itself, and the control that writes it.
    presence: Presence = Presence.online
    profile_decorations: ProfileDecorations = Field(default_factory=ProfileDecorations)
    week_starts_on: int = 0
    recent_tabs_limit: int = 20
    timezone: str = "UTC"
    overdue_notification_time: str = "21:00"
    email_initiative_addition: bool = True
    email_task_assignment: bool = True
    email_project_added: bool = True
    email_overdue_tasks: bool = True
    email_mentions: bool = True
    email_comment_reactions: bool = True
    push_initiative_addition: bool = True
    push_task_assignment: bool = True
    push_project_added: bool = True
    push_overdue_tasks: bool = True
    push_mentions: bool = True
    push_comment_reactions: bool = True
    email_direct_messages: bool = True
    push_direct_messages: bool = True
    email_posts: bool = True
    push_posts: bool = True
    email_events: bool = True
    push_events: bool = True
    email_event_reminders: bool = True
    push_event_reminders: bool = True
    event_reminder_minutes_before: Optional[int] = 15
    last_overdue_notification_at: Optional[datetime] = None
    last_task_assignment_digest_at: Optional[datetime] = None
    color_theme: str = "kobold"
    task_completion_visual_feedback: str = "none"
    task_completion_audio_feedback: bool = True
    task_completion_haptic_feedback: bool = True
    locale: str = "en"
    # True when the account has a linked external identity (SSO). Consumed by
    # the profile/deletion UI to hide the password confirmation, since SSO-only
    # accounts have no usable password to type in. Populated by the self
    # endpoints (/users/me and PATCH /users/me); defaults False elsewhere.
    has_federated_identity: bool = False
    initiative_roles: List["UserInitiativeRole"] = Field(default_factory=list)

    @computed_field(return_type=bool)  # type: ignore[misc]
    @property
    def can_create_guilds(self) -> bool:
        if not settings.DISABLE_GUILD_CREATION:
            return True
        # When disabled, only platform roles that manage guilds can create them.
        return Capability.GUILDS_MANAGE in capabilities_for(self.role)

    @computed_field(return_type=List[str])  # type: ignore[misc]
    @property
    def capabilities(self) -> List[str]:
        """Platform capabilities granted by this user's standing role.

        The frontend gates UI on these strings (single source of truth);
        see ``app.core.capabilities``.
        """
        return sorted(c.value for c in capabilities_for(self.role))


class UsernameClaim(SanitizedBaseModel):
    """The name part an account picks for itself.

    Available once, to an account whose handle was assigned rather than chosen
    (``username_chosen`` false) — every account created without a form gets one
    that way. The number behind the name is drawn server-side.
    """

    username: str = Field(max_length=64)


class AgeConfirmation(SanitizedBaseModel):
    """Someone saying when they were born, once.

    The date answers one question — are they old enough — and is then gone. It
    is never written to a column, never logged, and never put in an audit
    record; there is nowhere in the schema it could be kept. What the account
    keeps is that the question was answered and when
    (``users.age_confirmed_at``), which is what a deployment needs to show it
    asked.

    Asking for a date rather than offering a box to tick is the difference
    between a question and a formality: a box says what the answer should be
    before it is given.
    """

    birthdate: date


class UserInitiativeRole(SanitizedBaseModel):
    initiative_id: int
    initiative_name: str
    # The role's own name; ``None`` when the role it pointed at was deleted.
    role: Optional[str] = None


class UserSelfUpdate(SanitizedBaseModel):
    full_name: Optional[TitleStr] = None
    password: Optional[RawTextStr] = Field(default=None, max_length=256)
    # Required to set a new ``password`` (verified server-side). Exempt for
    # OIDC-only accounts, which have no local password to confirm.
    current_password: Optional[RawTextStr] = Field(default=None, max_length=256)
    avatar_url: Optional[str] = None
    # Sending ``null`` takes the status off; leaving it out leaves it alone.
    custom_status: Optional[CustomStatus] = None
    presence: Optional[Presence] = None
    # The whole set at once rather than one key at a time: a profile wears a
    # look, and a partial write would have no way to say "take the frame off".
    profile_decorations: Optional[ProfileDecorations] = None
    week_starts_on: Optional[int] = None
    recent_tabs_limit: Optional[int] = Field(default=None, ge=1, le=100)
    timezone: Optional[str] = None
    overdue_notification_time: Optional[str] = None
    email_initiative_addition: Optional[bool] = None
    email_task_assignment: Optional[bool] = None
    email_project_added: Optional[bool] = None
    email_overdue_tasks: Optional[bool] = None
    email_mentions: Optional[bool] = None
    email_comment_reactions: Optional[bool] = None
    push_initiative_addition: Optional[bool] = None
    push_task_assignment: Optional[bool] = None
    push_project_added: Optional[bool] = None
    push_overdue_tasks: Optional[bool] = None
    push_mentions: Optional[bool] = None
    push_comment_reactions: Optional[bool] = None
    email_direct_messages: Optional[bool] = None
    push_direct_messages: Optional[bool] = None
    email_posts: Optional[bool] = None
    push_posts: Optional[bool] = None
    email_events: Optional[bool] = None
    push_events: Optional[bool] = None
    email_event_reminders: Optional[bool] = None
    push_event_reminders: Optional[bool] = None
    event_reminder_minutes_before: Optional[int] = None
    color_theme: Optional[str] = None
    task_completion_visual_feedback: Optional[str] = None
    task_completion_audio_feedback: Optional[bool] = None
    task_completion_haptic_feedback: Optional[bool] = None
    locale: Optional[str] = Field(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")


class AccountDeletionRequest(SanitizedBaseModel):
    """Request from a user to deactivate or anonymize (soft-delete) their own account.

    `hard_delete` is intentionally not allowed from this self-service endpoint;
    only platform admins can purge a row, and they do so via the admin endpoint.
    """

    action: Literal["deactivate", "soft_delete"]
    password: RawTextStr
    confirmation_text: str


class DeletionEligibilityResponse(SanitizedBaseModel):
    """Response indicating whether user can be deleted and any blockers"""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    can_delete: bool
    blockers: List[str] = Field(default_factory=list)
    last_admin_guilds: List[str] = Field(default_factory=list)


class AccountDeletionResponse(SanitizedBaseModel):
    """Response after a deactivate / anonymize / hard-delete action."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    success: bool
    action: str
    message: str
