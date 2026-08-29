from datetime import datetime
from typing import List, Literal, Optional

from pydantic import ConfigDict, EmailStr, Field, computed_field

from app.schemas.base import RawTextStr, SanitizedBaseModel

from app.core.capabilities import Capability, capabilities_for
from app.models.platform.user import UserRole, UserStatus
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
    full_name: Optional[str] = None
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


class UserPublic(SanitizedBaseModel):
    """Public user information exposed to other users.

    Includes ``status`` so the frontend can render the "Deleted user #{id}"
    placeholder for anonymized accounts wherever a person appears
    (comment authors, task assignees, mentions, calendar attendees).
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    email: EmailStr
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status: UserStatus = UserStatus.active


class UserGuildMember(UserPublic):
    """User information for guild member management (includes role/status but not personal settings)"""

    role: UserRole  # Platform role
    guild_role: Optional[str] = None  # Guild role (admin/member) - set by endpoint
    oidc_managed: bool = False  # Whether membership is managed via OIDC claim mappings
    status: UserStatus
    email_verified: bool
    created_at: datetime
    initiative_roles: List["UserInitiativeRole"] = Field(default_factory=list)


class UserSummary(SanitizedBaseModel):
    """Slim user projection for typeahead and picker surfaces.

    Drops the fields pickers never read — email, platform/guild role,
    ``initiative_roles`` (an N+1 enrichment on the full roster), and
    timestamps — while keeping the avatar so members still render with a
    face. The payload is bounded by pagination on the endpoints that serve
    it, not by dropping the avatar.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status: UserStatus = UserStatus.active


class UserSummaryListResponse(SanitizedBaseModel):
    """Paginated envelope for the slim user search/typeahead endpoints."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[UserSummary]
    total_count: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool


class UserRead(UserBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    status: UserStatus
    email_verified: bool
    created_at: datetime
    updated_at: datetime
    avatar_url: Optional[str] = None
    week_starts_on: int = 0
    recent_tabs_limit: int = 20
    timezone: str = "UTC"
    overdue_notification_time: str = "21:00"
    email_initiative_addition: bool = True
    email_task_assignment: bool = True
    email_project_added: bool = True
    email_overdue_tasks: bool = True
    email_mentions: bool = True
    push_initiative_addition: bool = True
    push_task_assignment: bool = True
    push_project_added: bool = True
    push_overdue_tasks: bool = True
    push_mentions: bool = True
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


class UserInitiativeRole(SanitizedBaseModel):
    initiative_id: int
    initiative_name: str
    # The role's own name; ``None`` when the role it pointed at was deleted.
    role: Optional[str] = None


class UserSelfUpdate(SanitizedBaseModel):
    full_name: Optional[str] = None
    password: Optional[RawTextStr] = Field(default=None, max_length=256)
    # Required to set a new ``password`` (verified server-side). Exempt for
    # OIDC-only accounts, which have no local password to confirm.
    current_password: Optional[RawTextStr] = Field(default=None, max_length=256)
    avatar_url: Optional[str] = None
    week_starts_on: Optional[int] = None
    recent_tabs_limit: Optional[int] = Field(default=None, ge=1, le=100)
    timezone: Optional[str] = None
    overdue_notification_time: Optional[str] = None
    email_initiative_addition: Optional[bool] = None
    email_task_assignment: Optional[bool] = None
    email_project_added: Optional[bool] = None
    email_overdue_tasks: Optional[bool] = None
    email_mentions: Optional[bool] = None
    push_initiative_addition: Optional[bool] = None
    push_task_assignment: Optional[bool] = None
    push_project_added: Optional[bool] = None
    push_overdue_tasks: Optional[bool] = None
    push_mentions: Optional[bool] = None
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
