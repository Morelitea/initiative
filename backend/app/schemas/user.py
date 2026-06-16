from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import ConfigDict, EmailStr, Field, computed_field

from app.schemas.base import RawTextStr, SanitizedBaseModel

from app.core.capabilities import Capability, capabilities_for
from app.models.initiative import InitiativeRole
from app.models.user import UserRole, UserStatus
from app.core.config import settings

# ``avatar_base64`` is a ``RawTextStr`` so it skips the global 8 KiB plain-text
# cap (it holds an inline data URI, not free text). Left unbounded it is a
# stored-amplification vector: the SPA sends whatever image the user picks with
# no client-side downscale (``UserSettingsProfilePage`` reads the file straight
# through ``FileReader.readAsDataURL``), and the value is echoed to every guild
# member via presence/member listings. ~700 KB of base64 decodes to ~512 KB of
# image bytes (4/3 inflation) once the ``data:image/...;base64,`` prefix is
# accounted for — generous for any reasonable avatar while bounding the blast
# radius. Oversized payloads are rejected with 422.
MAX_AVATAR_BASE64_LENGTH = 700_000


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


class UserUpdate(SanitizedBaseModel):
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    password: Optional[RawTextStr] = Field(default=None, max_length=256)
    status: Optional[UserStatus] = None
    avatar_base64: Optional[RawTextStr] = Field(
        default=None, max_length=MAX_AVATAR_BASE64_LENGTH
    )
    avatar_url: Optional[str] = None
    week_starts_on: Optional[int] = None
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
    # No max_length here: this is a RESPONSE schema, and FastAPI validates
    # response models, so a cap would 500 every endpoint returning a user whose
    # avatar predates the write-side cap. The bound is enforced on the write
    # schemas (UserUpdate / UserSelfUpdate); legacy oversized rows shrink as
    # they are next updated.
    avatar_base64: Optional[RawTextStr] = None
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


class UserRead(UserBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    status: UserStatus
    email_verified: bool
    created_at: datetime
    updated_at: datetime
    # Response schema — uncapped for the same legacy-row reason as UserPublic.
    avatar_base64: Optional[RawTextStr] = None
    avatar_url: Optional[str] = None
    week_starts_on: int = 0
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
    # Non-null for users provisioned via OIDC SSO; consumed by the
    # self-deletion dialog so it can hide the password gate, since
    # OIDC-only accounts have no usable password to type in.
    oidc_sub: Optional[str] = None
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


class UserInDB(UserRead):
    hashed_password: str


class UserInitiativeRole(SanitizedBaseModel):
    initiative_id: int
    initiative_name: str
    role: InitiativeRole


class UserSelfUpdate(SanitizedBaseModel):
    full_name: Optional[str] = None
    password: Optional[RawTextStr] = Field(default=None, max_length=256)
    avatar_base64: Optional[RawTextStr] = Field(
        default=None, max_length=MAX_AVATAR_BASE64_LENGTH
    )
    avatar_url: Optional[str] = None
    week_starts_on: Optional[int] = None
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


class ProjectBasic(SanitizedBaseModel):
    """Basic project information for deletion flow"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    initiative_id: int
    # The owning guild. Projects live in per-guild schemas, so the deletion /
    # transfer UI needs this to call the guild-scoped member-picker and
    # transfer endpoints (which now require ``guild_id``).
    guild_id: int


class AccountDeletionRequest(SanitizedBaseModel):
    """Request from a user to deactivate or anonymize (soft-delete) their own account.

    `hard_delete` is intentionally not allowed from this self-service endpoint;
    only platform admins can purge a row, and they do so via the admin endpoint.
    """

    action: Literal["deactivate", "soft_delete"]
    password: RawTextStr
    confirmation_text: str
    # Keyed by "guild_id:project_id" (NOT bare project_id): under schema-per-guild
    # the same numeric project id can exist in multiple guilds the user owns, so a
    # bare id would collide and transfer both to one recipient.
    project_transfers: Optional[Dict[str, int]] = None


class DeletionEligibilityResponse(SanitizedBaseModel):
    """Response indicating whether user can be deleted and any blockers"""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    can_delete: bool
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    owned_projects: List[ProjectBasic] = Field(default_factory=list)
    last_admin_guilds: List[str] = Field(default_factory=list)


class GuildRemovalProjectInfo(SanitizedBaseModel):
    """Per-project payload on ``GuildRemovalEligibilityResponse``.

    Bundles the candidate transfer recipients next to the project so
    the SPA can render the picker without a second round-trip. The
    leave-guild path uses ``GET /users/me/initiative-members/...``
    instead — but a guild admin removing someone may not themselves
    be a member of every initiative the target user belongs to, so
    that endpoint isn't always callable from this flow.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    initiative_id: int
    candidates: List[UserPublic] = Field(default_factory=list)


class GuildRemovalEligibilityResponse(SanitizedBaseModel):
    """Pre-flight info for ``DELETE /users/{user_id}`` (guild admin
    removes a member from their guild).

    Mirrors the leave-guild eligibility shape for the same reason: the
    SPA needs to know up-front whether the admin will be prompted to
    pick replacement owners for projects the target user owns. Without
    this, the existing one-click "remove member" path silently
    orphaned every project where the leaving user was sole owner.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    can_remove: bool
    sole_pm_initiatives: List[str] = Field(default_factory=list)
    owned_projects: List[GuildRemovalProjectInfo] = Field(default_factory=list)


class GuildRemovalRequest(SanitizedBaseModel):
    """Body for ``DELETE /users/{user_id}``.

    Every project the target user owns in the active guild must
    appear in exactly one of ``project_transfers`` (hand it to
    another active project manager) or ``project_deletions`` (send
    it to trash so the guild's retention window can purge it). The
    delete branch exists so an admin can still remove a user from a
    guild where no other project manager is available — without it,
    a sole-PM situation would leave the admin with a forever-disabled
    Remove button.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    project_transfers: Dict[int, int] = Field(default_factory=dict)
    project_deletions: List[int] = Field(default_factory=list)


class AccountDeletionResponse(SanitizedBaseModel):
    """Response after a deactivate / anonymize / hard-delete action."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    success: bool
    action: str
    message: str
