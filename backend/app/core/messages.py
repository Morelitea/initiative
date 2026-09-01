"""Centralized error message constants for API responses.

These constants are used as HTTPException detail strings. The frontend
maps these codes to localized user-facing messages via errors.json.
"""


class AuthMessages:
    EMAIL_ALREADY_REGISTERED = "EMAIL_ALREADY_REGISTERED"
    REGISTRATION_REQUIRES_INVITE = "REGISTRATION_REQUIRES_INVITE"
    UNABLE_TO_CREATE_USER = "UNABLE_TO_CREATE_USER"
    INCORRECT_CREDENTIALS = "INCORRECT_CREDENTIALS"
    INACTIVE_USER = "INACTIVE_USER"
    DEACTIVATED_USER = "DEACTIVATED_USER"
    ANONYMIZED_USER = "ANONYMIZED_USER"
    CANNOT_REACTIVATE_ANONYMIZED = "CANNOT_REACTIVATE_ANONYMIZED"
    HARD_DELETE_NOT_ALLOWED_HERE = "HARD_DELETE_NOT_ALLOWED_HERE"
    EMAIL_NOT_VERIFIED = "EMAIL_NOT_VERIFIED"
    TOKEN_NOT_FOUND = "TOKEN_NOT_FOUND"
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    INVALID_DEVICE_TOKEN = "INVALID_DEVICE_TOKEN"
    #: The action hands out authority, so it is taken while signed in rather
    #: than through a standing credential (an API key, a device token, an app
    #: acting on someone's behalf).
    SESSION_REQUIRED = "SESSION_REQUIRED"
    COULD_NOT_VALIDATE_CREDENTIALS = "COULD_NOT_VALIDATE_CREDENTIALS"
    INVALID_TOKEN_PAYLOAD = "INVALID_TOKEN_PAYLOAD"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    INSUFFICIENT_PRIVILEGES = "INSUFFICIENT_PRIVILEGES"
    INVALID_TOKEN = "INVALID_TOKEN"
    # Generic refresh rejection: unknown / expired / reused all map here so the
    # client learns only "re-authenticate", never that a replay was detected.
    INVALID_REFRESH_TOKEN = "INVALID_REFRESH_TOKEN"
    INVALID_OR_EXPIRED_TOKEN = "INVALID_OR_EXPIRED_TOKEN"
    SMTP_NOT_CONFIGURED = "SMTP_NOT_CONFIGURED"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    CAPTCHA_INVALID = "CAPTCHA_INVALID"


class GuildMessages:
    # The frontend error map still carries NO_GUILD_MEMBERSHIP for servers
    # that predate path-based guild resolution; the backend itself only
    # raises GUILD_ACCESS_DENIED.
    GUILD_ACCESS_DENIED = "GUILD_ACCESS_DENIED"
    GUILD_AUTH_STEP_UP_REQUIRED = "GUILD_AUTH_STEP_UP_REQUIRED"
    GUILD_AUTH_NOT_ENABLED = "GUILD_AUTH_NOT_ENABLED"
    GUILD_AUTH_POLICY_INVALID_PROVIDER = "GUILD_AUTH_POLICY_INVALID_PROVIDER"
    GUILD_AUTH_POLICY_SELF_UNSATISFIED = "GUILD_AUTH_POLICY_SELF_UNSATISFIED"
    GUILD_PERMISSION_REQUIRED = "GUILD_PERMISSION_REQUIRED"
    GUILD_ADMIN_REQUIRED = "GUILD_ADMIN_REQUIRED"
    GUILD_CREATION_DISABLED = "GUILD_CREATION_DISABLED"
    GUILD_NAME_REQUIRED = "GUILD_NAME_REQUIRED"
    # Naming another user as a new guild's admin is platform-staff only.
    GUILD_OWNER_REQUIRES_CAPABILITY = "GUILD_OWNER_REQUIRES_CAPABILITY"
    # ...and that user has to exist already; we never create one.
    GUILD_OWNER_NOT_FOUND = "GUILD_OWNER_NOT_FOUND"
    GUILD_NOT_FOUND = "GUILD_NOT_FOUND"
    GUILD_MEMBERSHIP_CREATE_FAILED = "GUILD_MEMBERSHIP_CREATE_FAILED"
    GUILD_PROVISION_FAILED = "GUILD_PROVISION_FAILED"
    GUILD_DELETE_FAILED = "GUILD_DELETE_FAILED"
    GUILD_MEMBERSHIP_MISSING = "GUILD_MEMBERSHIP_MISSING"
    GUILD_USER_LIMIT_REACHED = "GUILD_USER_LIMIT_REACHED"
    # Asked to join a guild that is not listed in the community directory (or
    # is no longer active). Reported as a 404 — an unlisted guild has published
    # nothing, its existence at a given id included.
    GUILD_NOT_A_COMMUNITY = "GUILD_NOT_A_COMMUNITY"
    # The three things a guild must be before it can be listed: on at least one
    # shelf, declared free of adult content, and able to admit anyone at all.
    GUILD_COMMUNITY_REQUIRES_CATEGORY = "GUILD_COMMUNITY_REQUIRES_CATEGORY"
    GUILD_COMMUNITY_CONTENT_NOT_DECLARED = "GUILD_COMMUNITY_CONTENT_NOT_DECLARED"
    GUILD_COMMUNITY_ADULT_CONTENT = "GUILD_COMMUNITY_ADULT_CONTENT"
    GUILD_COMMUNITY_REQUIRES_CAPACITY = "GUILD_COMMUNITY_REQUIRES_CAPACITY"
    # The deployment runs no community directory: an owner has not switched it
    # on. Distinct from the four rules above, which are about one guild — this
    # one says the surface does not exist here at all.
    COMMUNITY_DIRECTORY_DISABLED = "COMMUNITY_DIRECTORY_DISABLED"
    # A guild icon or banner rendition that is not one. Each names the rule it
    # broke, so the settings page can say what to do about it rather than
    # "that didn't work".
    IMAGE_EMPTY = "IMAGE_EMPTY"
    IMAGE_TOO_LARGE = "IMAGE_TOO_LARGE"
    IMAGE_INVALID = "IMAGE_INVALID"
    IMAGE_WRONG_SIZE = "IMAGE_WRONG_SIZE"
    IMAGE_WRONG_RATIO = "IMAGE_WRONG_RATIO"
    IMAGE_NOT_FOUND = "IMAGE_NOT_FOUND"
    BANNER_COLOR_INVALID = "BANNER_COLOR_INVALID"
    # Banner text is black or white; nothing between the two is offered.
    BANNER_TEXT_COLOR_INVALID = "BANNER_TEXT_COLOR_INVALID"
    # Banner artwork is not part of what this guild has; the colour is.
    BANNER_IMAGE_NOT_ENTITLED = "BANNER_IMAGE_NOT_ENTITLED"
    CANNOT_CHANGE_OWN_ROLE = "CANNOT_CHANGE_OWN_ROLE"
    # 'support' is synthesized for PAM grantees only; it is never a stored
    # guild-membership role, so it cannot be assigned via the role endpoints.
    GUILD_ROLE_NOT_ASSIGNABLE = "GUILD_ROLE_NOT_ASSIGNABLE"
    USER_NOT_FOUND_IN_GUILD = "USER_NOT_FOUND_IN_GUILD"
    CANNOT_DEMOTE_LAST_ADMIN = "CANNOT_DEMOTE_LAST_ADMIN"
    NOT_GUILD_MEMBER = "NOT_GUILD_MEMBER"
    CANNOT_LEAVE_LAST_ADMIN = "CANNOT_LEAVE_LAST_ADMIN"
    INVITE_NOT_FOUND = "INVITE_NOT_FOUND"
    INVITE_EXPIRED_OR_USED = "INVITE_EXPIRED_OR_USED"
    INVITE_EMAIL_MISMATCH = "INVITE_EMAIL_MISMATCH"
    INVITE_INVALID = "INVITE_INVALID"
    INVITE_EXPIRED = "INVITE_EXPIRED"
    INVITE_USED = "INVITE_USED"
    INVALID_PASSWORD = "GUILD_INVALID_PASSWORD"
    CONFIRMATION_MISMATCH = "GUILD_CONFIRMATION_MISMATCH"


class InitiativeMessages:
    NOT_FOUND = "INITIATIVE_NOT_FOUND"
    MANAGER_REQUIRED = "INITIATIVE_MANAGER_REQUIRED"
    NAME_EXISTS = "INITIATIVE_NAME_EXISTS"
    CANNOT_DELETE_DEFAULT = "INITIATIVE_CANNOT_DELETE_DEFAULT"
    NOT_A_MEMBER = "INITIATIVE_NOT_A_MEMBER"
    ROLE_NOT_FOUND = "INITIATIVE_ROLE_NOT_FOUND"
    ROLE_NAME_EXISTS = "INITIATIVE_ROLE_NAME_EXISTS"
    CANNOT_MODIFY_PM_PERMISSIONS = "INITIATIVE_CANNOT_MODIFY_PM_PERMISSIONS"
    CANNOT_CHANGE_BUILTIN_MANAGER = "INITIATIVE_CANNOT_CHANGE_BUILTIN_MANAGER"
    MUST_HAVE_MANAGER = "INITIATIVE_MUST_HAVE_MANAGER"
    USER_NOT_IN_GUILD = "INITIATIVE_USER_NOT_IN_GUILD"
    MEMBER_ROLE_NOT_FOUND = "INITIATIVE_MEMBER_ROLE_NOT_FOUND"
    MEMBER_NOT_FOUND = "INITIATIVE_MEMBER_NOT_FOUND"
    MUST_HAVE_PM = "INITIATIVE_MUST_HAVE_PM"
    CANNOT_DELETE_BUILTIN = "INITIATIVE_CANNOT_DELETE_BUILTIN"
    ROLE_HAS_MEMBERS = "INITIATIVE_ROLE_HAS_MEMBERS"
    # A guild admin already has full access to every initiative; they may only
    # hold the manager role (for manager-style features), never a standard
    # member or custom role.
    GUILD_ADMIN_ROLE_RESTRICTED = "INITIATIVE_GUILD_ADMIN_ROLE_RESTRICTED"
    # "Full access" (override_share_restrictions) may be changed only by a guild
    # admin (so an initiative role can't escalate itself), and only on the
    # built-in project_manager role.
    OVERRIDE_REQUIRES_GUILD_ADMIN = "INITIATIVE_OVERRIDE_REQUIRES_GUILD_ADMIN"
    OVERRIDE_PM_ONLY = "INITIATIVE_OVERRIDE_PM_ONLY"
    # Asked to self-join an initiative whose join policy is not 'open'. Reported
    # for 'private' and 'request' alike, so the answer says only "not by this
    # route" — a request-policy initiative is discoverable through the directory.
    NOT_JOINABLE = "INITIATIVE_NOT_JOINABLE"
    # Auto-join enrols new guild members automatically, so it is only coherent on
    # an initiative they could also have found and joined themselves ('open').
    AUTO_JOIN_REQUIRES_OPEN = "INITIATIVE_AUTO_JOIN_REQUIRES_OPEN"
    # Auto-join shapes onboarding for the whole guild, so only a guild admin sets
    # it — unlike join_policy, which any initiative manager may change.
    AUTO_JOIN_ADMIN_ONLY = "INITIATIVE_AUTO_JOIN_ADMIN_ONLY"
    # A PAM grant confers content read/write for a window; a membership row
    # would outlast it, so joining is for real guild members.
    GRANT_CANNOT_MANAGE_MEMBERS = "INITIATIVE_GRANT_CANNOT_MANAGE_MEMBERS"
    # Asked to knock on an initiative whose join policy is not 'request'.
    # Reported for 'private' and 'open' alike, so — like NOT_JOINABLE — the
    # answer says only "not by this route".
    NOT_REQUESTABLE = "INITIATIVE_NOT_REQUESTABLE"
    # Nothing to ask for: the caller already holds a membership row here.
    ALREADY_A_MEMBER = "INITIATIVE_ALREADY_A_MEMBER"
    # A guild admin reaches every initiative in their guild by standing, and may
    # only ever hold a manager role in one — so there is nothing for them to
    # request, and no request that could be approved into a permitted row.
    GUILD_ADMIN_NEED_NOT_REQUEST = "INITIATIVE_GUILD_ADMIN_NEED_NOT_REQUEST"
    # One live request per user per initiative (uq_initiative_join_requests_pending).
    JOIN_REQUEST_ALREADY_PENDING = "INITIATIVE_JOIN_REQUEST_ALREADY_PENDING"
    JOIN_REQUEST_NOT_FOUND = "INITIATIVE_JOIN_REQUEST_NOT_FOUND"
    # Approve/deny act on a pending row only; a resolved one is history.
    JOIN_REQUEST_ALREADY_RESOLVED = "INITIATIVE_JOIN_REQUEST_ALREADY_RESOLVED"


class FilterPresetMessages:
    NOT_FOUND = "FILTER_PRESET_NOT_FOUND"
    DUPLICATE_ID = "FILTER_PRESET_DUPLICATE_ID"
    SLUG_TAKEN = "FILTER_PRESET_SLUG_TAKEN"
    INVALID_FILTERS = "FILTER_PRESET_INVALID_FILTERS"
    LIMIT_REACHED = "FILTER_PRESET_LIMIT_REACHED"


class ProjectMessages:
    NOT_FOUND = "PROJECT_NOT_FOUND"
    INITIATIVE_NOT_FOUND = "PROJECT_INITIATIVE_NOT_FOUND"
    IS_ARCHIVED = "PROJECT_IS_ARCHIVED"
    OWNER_REQUIRED = "PROJECT_OWNER_REQUIRED"
    NO_ACCESS = "PROJECT_NO_ACCESS"
    WRITE_ACCESS_REQUIRED = "PROJECT_WRITE_ACCESS_REQUIRED"
    INVALID_TEMPLATE = "PROJECT_INVALID_TEMPLATE"
    INITIATIVE_REQUIRED = "PROJECT_INITIATIVE_REQUIRED"
    CREATE_PERMISSION_REQUIRED = "PROJECT_CREATE_PERMISSION_REQUIRED"
    PIN_PERMISSION_REQUIRED = "PROJECT_PIN_PERMISSION_REQUIRED"
    # Configuring the project itself (pinning, default view, filter
    # presets) — a project manager, the project owner, or a guild admin.
    ADMIN_REQUIRED = "PROJECT_ADMIN_REQUIRED"
    DOCUMENT_NOT_FOUND = "PROJECT_DOCUMENT_NOT_FOUND"
    DOCUMENT_WRONG_INITIATIVE = "PROJECT_DOCUMENT_WRONG_INITIATIVE"
    CANNOT_ASSIGN_OWNER = "PROJECT_CANNOT_ASSIGN_OWNER"
    OWNER_HAS_FULL_ACCESS = "PROJECT_OWNER_HAS_FULL_ACCESS"
    CANNOT_MODIFY_OWNER = "PROJECT_CANNOT_MODIFY_OWNER"
    PERMISSION_NOT_FOUND = "PROJECT_PERMISSION_NOT_FOUND"
    CANNOT_REMOVE_OWNER = "PROJECT_CANNOT_REMOVE_OWNER"
    CANNOT_ASSIGN_OWNER_TO_ROLE = "PROJECT_CANNOT_ASSIGN_OWNER_TO_ROLE"
    ROLE_WRONG_INITIATIVE = "PROJECT_ROLE_WRONG_INITIATIVE"
    ROLE_PERMISSION_NOT_FOUND = "PROJECT_ROLE_PERMISSION_NOT_FOUND"
    # A PAM grant confers content read/write only, never access-control
    # management (adding/removing members or changing permission levels).
    GRANT_CANNOT_MANAGE_MEMBERS = "PROJECT_GRANT_CANNOT_MANAGE_MEMBERS"


class TaskMessages:
    NOT_FOUND = "TASK_NOT_FOUND"
    MISSING_AFTER_CREATE = "TASK_MISSING_AFTER_CREATE"
    MISSING_AFTER_UPDATE = "TASK_MISSING_AFTER_UPDATE"
    MISSING_AFTER_MOVE = "TASK_MISSING_AFTER_MOVE"
    ALREADY_IN_PROJECT = "TASK_ALREADY_IN_PROJECT"
    CANNOT_MOVE_TO_TEMPLATE = "TASK_CANNOT_MOVE_TO_TEMPLATE"
    PROJECT_MISMATCH = "TASK_PROJECT_MISMATCH"
    STATUS_NOT_FOUND = "TASK_STATUS_NOT_FOUND_FOR_PROJECT"
    ASSIGNEES_NOT_FOUND = "TASK_ASSIGNEES_NOT_FOUND"
    INVALID_ASSIGNEE_ID = "TASK_INVALID_ASSIGNEE_ID"
    DUPLICATE_NOT_FOUND = "TASK_DUPLICATE_NOT_FOUND"


class SubtaskMessages:
    NOT_FOUND = "SUBTASK_NOT_FOUND"
    NOT_FOUND_FOR_TASK = "SUBTASK_NOT_FOUND_FOR_TASK"
    CONTENT_EMPTY = "SUBTASK_CONTENT_EMPTY"


class TaskStatusMessages:
    NOT_FOUND = "TASK_STATUS_NOT_FOUND"
    DUPLICATE_ID = "TASK_STATUS_DUPLICATE_ID"
    CANNOT_REMOVE_LAST = "TASK_STATUS_CANNOT_REMOVE_LAST"
    FALLBACK_REQUIRED = "TASK_STATUS_FALLBACK_REQUIRED"
    FALLBACK_MUST_DIFFER = "TASK_STATUS_FALLBACK_MUST_DIFFER"
    FALLBACK_CATEGORY_MISMATCH = "TASK_STATUS_FALLBACK_CATEGORY_MISMATCH"


class OidcMessages:
    OIDC_NOT_ENABLED = "OIDC_NOT_ENABLED"
    OIDC_METADATA_INCOMPLETE = "OIDC_METADATA_INCOMPLETE"
    REGISTRATION_DISABLED = "OIDC_REGISTRATION_DISABLED"
    EMAIL_UNVERIFIED = "OIDC_EMAIL_UNVERIFIED"
    ACCOUNT_INACTIVE = "OIDC_ACCOUNT_INACTIVE"


class AuthProviderMessages:
    NOT_FOUND = "AUTH_PROVIDER_NOT_FOUND"
    SLUG_RESERVED = "AUTH_PROVIDER_SLUG_RESERVED"
    SLUG_TAKEN = "AUTH_PROVIDER_SLUG_TAKEN"
    IN_USE = "AUTH_PROVIDER_IN_USE"


class TagMessages:
    NOT_FOUND = "TAG_NOT_FOUND"
    NAME_ALREADY_EXISTS = "TAG_NAME_ALREADY_EXISTS"
    # Shared by every set-tags / bulk-tags surface: one or more of the
    # submitted tag ids does not resolve to an active tag in this guild.
    INVALID_TAG_IDS = "INVALID_TAG_IDS"


class PropertyMessages:
    DEFINITION_NOT_FOUND = "PROPERTY_DEFINITION_NOT_FOUND"
    NAME_ALREADY_EXISTS = "PROPERTY_NAME_ALREADY_EXISTS"
    TYPE_CHANGE_BLOCKED = "PROPERTY_TYPE_CHANGE_BLOCKED"
    INVALID_VALUE_FOR_TYPE = "PROPERTY_INVALID_VALUE_FOR_TYPE"
    OPTION_NOT_IN_DEFINITION = "PROPERTY_OPTION_NOT_IN_DEFINITION"
    USER_NOT_IN_INITIATIVE = "PROPERTY_USER_NOT_IN_INITIATIVE"
    NOT_INITIATIVE_MEMBER = "PROPERTY_NOT_INITIATIVE_MEMBER"
    OPTIONS_REQUIRED = "PROPERTY_OPTIONS_REQUIRED"
    DUPLICATE_OPTION_VALUE = "PROPERTY_DUPLICATE_OPTION_VALUE"


class AttachmentMessages:
    IMAGE_ONLY = "ATTACHMENT_IMAGE_ONLY"
    FILE_EMPTY = "ATTACHMENT_FILE_EMPTY"
    INVALID_IMAGE = "ATTACHMENT_INVALID_IMAGE"
    TOO_LARGE = "ATTACHMENT_TOO_LARGE"
    STORAGE_QUOTA_EXCEEDED = "ATTACHMENT_STORAGE_QUOTA_EXCEEDED"


class DocumentMessages:
    NOT_FOUND = "DOCUMENT_NOT_FOUND"
    GRANT_CANNOT_MANAGE_MEMBERS = "DOCUMENT_GRANT_CANNOT_MANAGE_MEMBERS"
    INITIATIVE_NOT_FOUND = "DOCUMENT_INITIATIVE_NOT_FOUND"
    INITIATIVE_MEMBERSHIP_REQUIRED = "DOCUMENT_INITIATIVE_MEMBERSHIP_REQUIRED"
    PERMISSION_REQUIRED = "DOCUMENT_PERMISSION_REQUIRED"
    MANAGER_REQUIRED = "DOCUMENT_MANAGER_REQUIRED"
    WRITE_ACCESS_REQUIRED = "DOCUMENT_WRITE_ACCESS_REQUIRED"
    OWNER_REQUIRED = "DOCUMENT_OWNER_REQUIRED"
    NO_ACCESS = "DOCUMENT_NO_ACCESS"
    NAME_ALREADY_EXISTS = "DOCUMENT_NAME_ALREADY_EXISTS"
    TOO_MANY_IDS = "DOCUMENT_TOO_MANY_IDS"
    NAME_REQUIRED = "DOCUMENT_NAME_REQUIRED"
    CANNOT_ASSIGN_OWNER = "DOCUMENT_CANNOT_ASSIGN_OWNER"
    USER_MUST_BE_MEMBER = "DOCUMENT_USER_MUST_BE_MEMBER"
    CANNOT_MODIFY_OWNER = "DOCUMENT_CANNOT_MODIFY_OWNER"
    PERMISSION_NOT_FOUND = "DOCUMENT_PERMISSION_NOT_FOUND"
    CANNOT_REMOVE_OWNER = "DOCUMENT_CANNOT_REMOVE_OWNER"
    CANNOT_ASSIGN_OWNER_TO_ROLE = "DOCUMENT_CANNOT_ASSIGN_OWNER_TO_ROLE"
    ROLE_WRONG_INITIATIVE = "DOCUMENT_ROLE_WRONG_INITIATIVE"
    ROLE_PERMISSION_NOT_FOUND = "DOCUMENT_ROLE_PERMISSION_NOT_FOUND"
    AI_NATIVE_ONLY = "DOCUMENT_AI_NATIVE_ONLY"
    SMART_LINK_URL_REQUIRED = "DOCUMENT_SMART_LINK_URL_REQUIRED"
    SPREADSHEET_INVALID_PAYLOAD = "DOCUMENT_SPREADSHEET_INVALID_PAYLOAD"
    SMART_LINK_URL_INVALID = "DOCUMENT_SMART_LINK_URL_INVALID"
    NOT_A_FILE_DOCUMENT = "DOCUMENT_NOT_A_FILE_DOCUMENT"
    VERSION_NOT_FOUND = "DOCUMENT_VERSION_NOT_FOUND"
    CANNOT_DELETE_LAST_VERSION = "DOCUMENT_CANNOT_DELETE_LAST_VERSION"
    VERSION_TYPE_MISMATCH = "DOCUMENT_VERSION_TYPE_MISMATCH"
    VERSION_CONFLICT = "DOCUMENT_VERSION_CONFLICT"
    INVALID_FILE = "DOCUMENT_INVALID_FILE"
    FILE_TOO_LARGE = "DOCUMENT_FILE_TOO_LARGE"


class CommentMessages:
    NOT_FOUND = "COMMENT_NOT_FOUND"
    PERMISSION_DENIED = "COMMENT_PERMISSION_DENIED"
    VALIDATION_ERROR = "COMMENT_VALIDATION_ERROR"
    PARENT_NOT_FOUND = "COMMENT_PARENT_NOT_FOUND"
    TASK_NOT_FOUND = "COMMENT_TASK_NOT_FOUND"
    DOCUMENT_NOT_FOUND = "COMMENT_DOCUMENT_NOT_FOUND"
    TARGET_NOT_FOUND = "COMMENT_TARGET_NOT_FOUND"
    PARENT_MISMATCH = "COMMENT_PARENT_MISMATCH"
    PROVIDE_ONE_ENTITY = "COMMENT_PROVIDE_ONE_ENTITY"
    AUTHOR_ONLY_EDIT = "COMMENT_AUTHOR_ONLY_EDIT"
    AUTHOR_ONLY_DELETE = "COMMENT_AUTHOR_ONLY_DELETE"
    NOT_LINKED = "COMMENT_NOT_LINKED"
    COMMENTS_DISABLED = "COMMENTS_DISABLED"


class ReactionMessages:
    TARGET_NOT_FOUND = "REACTION_TARGET_NOT_FOUND"
    PERMISSION_DENIED = "REACTION_PERMISSION_DENIED"
    NOT_FOUND = "REACTION_NOT_FOUND"
    INVALID_EMOJI = "REACTION_INVALID_EMOJI"
    TOO_MANY = "REACTION_TOO_MANY"


class SettingsMessages:
    PROVIDE_TEST_EMAIL = "SETTINGS_PROVIDE_TEST_EMAIL"
    SMTP_INCOMPLETE = "SETTINGS_SMTP_INCOMPLETE"
    # Generic code for a failed SMTP delivery — the raw exception (which can
    # carry the SMTP host, port, or server banner) is logged server-side only
    # and never returned to the client (pentest SEC-16).
    EMAIL_SEND_FAILED = "SETTINGS_EMAIL_SEND_FAILED"
    MAPPING_NOT_FOUND = "SETTINGS_MAPPING_NOT_FOUND"
    INVALID_TARGET_TYPE = "SETTINGS_INVALID_TARGET_TYPE"
    INVALID_GUILD_ROLE = "SETTINGS_INVALID_GUILD_ROLE"
    GUILD_NOT_FOUND = "SETTINGS_GUILD_NOT_FOUND"
    INITIATIVE_ID_REQUIRED = "SETTINGS_INITIATIVE_ID_REQUIRED"
    INITIATIVE_ROLE_ID_REQUIRED = "SETTINGS_INITIATIVE_ROLE_ID_REQUIRED"
    INITIATIVE_NOT_FOUND = "SETTINGS_INITIATIVE_NOT_FOUND"
    INITIATIVE_WRONG_GUILD = "SETTINGS_INITIATIVE_WRONG_GUILD"
    INITIATIVE_ROLE_NOT_FOUND = "SETTINGS_INITIATIVE_ROLE_NOT_FOUND"
    INITIATIVE_FIELDS_REQUIRED = "SETTINGS_INITIATIVE_FIELDS_REQUIRED"
    # Object storage
    STORAGE_S3_INCOMPLETE = "SETTINGS_STORAGE_S3_INCOMPLETE"
    STORAGE_TEST_FAILED = "SETTINGS_STORAGE_TEST_FAILED"
    STORAGE_BACKFILL_RUNNING = "SETTINGS_STORAGE_BACKFILL_RUNNING"
    STORAGE_BACKFILL_NOT_CONFIGURED = "SETTINGS_STORAGE_BACKFILL_NOT_CONFIGURED"


class AdminMessages:
    USER_NOT_FOUND = "ADMIN_USER_NOT_FOUND"
    CANNOT_RESET_INACTIVE = "ADMIN_CANNOT_RESET_INACTIVE"
    USER_ALREADY_ACTIVE = "ADMIN_USER_ALREADY_ACTIVE"
    CANNOT_REACTIVATE_ANONYMIZED = "ADMIN_CANNOT_REACTIVATE_ANONYMIZED"
    CANNOT_SUSPEND_SELF = "ADMIN_CANNOT_SUSPEND_SELF"
    CANNOT_SUSPEND_INACTIVE = "ADMIN_CANNOT_SUSPEND_INACTIVE"
    ALREADY_ANONYMIZED = "ADMIN_ALREADY_ANONYMIZED"
    CANNOT_CHANGE_ROLE_INACTIVE = "ADMIN_CANNOT_CHANGE_ROLE_INACTIVE"
    CANNOT_CHANGE_OWN_ROLE = "ADMIN_CANNOT_CHANGE_OWN_ROLE"
    CANNOT_DEMOTE_LAST_ADMIN = "ADMIN_CANNOT_DEMOTE_LAST_ADMIN"
    CANNOT_DEMOTE_LAST_OWNER = "ADMIN_CANNOT_DEMOTE_LAST_OWNER"
    CANNOT_ASSIGN_HIGHER_ROLE = "ADMIN_CANNOT_ASSIGN_HIGHER_ROLE"
    USE_SELF_DELETION = "ADMIN_USE_SELF_DELETION"
    CANNOT_DELETE_LAST_ADMIN = "ADMIN_CANNOT_DELETE_LAST_ADMIN"
    CANNOT_DELETE_LAST_OWNER = "ADMIN_CANNOT_DELETE_LAST_OWNER"
    CANNOT_DELETE_SELF = "ADMIN_CANNOT_DELETE_SELF"
    USER_CANNOT_BE_DELETED = "ADMIN_USER_CANNOT_BE_DELETED"
    GUILD_NOT_FOUND = "ADMIN_GUILD_NOT_FOUND"
    # Operator guild deletion is scoped to resolving a user-deletion blocker:
    # the guild must be one the named user is the SOLE admin of. Any other guild
    # is refused (operators reach a live guild only via a break-glass grant).
    GUILD_NOT_A_DELETION_BLOCKER = "ADMIN_GUILD_NOT_A_DELETION_BLOCKER"
    USER_NOT_IN_GUILD = "ADMIN_USER_NOT_IN_GUILD"
    CANNOT_DEMOTE_LAST_GUILD_ADMIN = "ADMIN_CANNOT_DEMOTE_LAST_GUILD_ADMIN"
    INITIATIVE_NOT_FOUND = "ADMIN_INITIATIVE_NOT_FOUND"
    USER_NOT_IN_INITIATIVE = "ADMIN_USER_NOT_IN_INITIATIVE"
    CANNOT_DEMOTE_LAST_PM = "ADMIN_CANNOT_DEMOTE_LAST_PM"
    ROLE_NOT_FOUND = "ADMIN_ROLE_NOT_FOUND"


class AccessGrantMessages:
    NOT_FOUND = "ACCESS_GRANT_NOT_FOUND"
    GUILD_NOT_FOUND = "ACCESS_GRANT_GUILD_NOT_FOUND"
    DURATION_TOO_LONG = "ACCESS_GRANT_DURATION_TOO_LONG"
    ALREADY_MEMBER = "ACCESS_GRANT_ALREADY_MEMBER"
    OVERLAPPING_GRANT = "ACCESS_GRANT_OVERLAPPING"
    NOT_PENDING = "ACCESS_GRANT_NOT_PENDING"
    NOT_ACTIVE = "ACCESS_GRANT_NOT_ACTIVE"
    CANNOT_APPROVE_OWN = "ACCESS_GRANT_CANNOT_APPROVE_OWN"
    CANNOT_CANCEL_OTHERS = "ACCESS_GRANT_CANNOT_CANCEL_OTHERS"
    # Break-glass (self-approved, data.bypass holders): a live grant for this
    # guild already exists, so there's nothing to self-issue.
    ALREADY_LIVE = "ACCESS_GRANT_ALREADY_LIVE"


class PasswordMessages:
    TOO_SHORT = "PASSWORD_TOO_SHORT"
    BREACHED = "PASSWORD_BREACHED"


class UserMessages:
    CANNOT_DELETE_LAST_ADMIN = "USER_CANNOT_DELETE_LAST_ADMIN"
    INVALID_PASSWORD = "USER_INVALID_PASSWORD"
    CONFIRMATION_MISMATCH = "USER_CONFIRMATION_MISMATCH"
    CANNOT_DELETE = "USER_CANNOT_DELETE"
    MISSING_PROJECT_TRANSFERS = "USER_MISSING_PROJECT_TRANSFERS"
    API_KEY_NOT_FOUND = "USER_API_KEY_NOT_FOUND"
    API_KEY_READ_ONLY = "USER_API_KEY_READ_ONLY"
    API_KEY_GUILD_FORBIDDEN = "USER_API_KEY_GUILD_FORBIDDEN"
    USERNAME_ALREADY_CHOSEN = "USERNAME_ALREADY_CHOSEN"
    CURRENT_PASSWORD_REQUIRED = "USER_CURRENT_PASSWORD_REQUIRED"
    CURRENT_PASSWORD_INCORRECT = "USER_CURRENT_PASSWORD_INCORRECT"
    INVALID_TIMEZONE = "USER_INVALID_TIMEZONE"
    INVALID_TIME_FORMAT = "USER_INVALID_TIME_FORMAT"
    INVALID_WEEK_START = "USER_INVALID_WEEK_START"
    INVALID_REMINDER_MINUTES = "USER_INVALID_REMINDER_MINUTES"
    INVALID_TASK_COMPLETION_VISUAL_FEEDBACK = (
        "USER_INVALID_TASK_COMPLETION_VISUAL_FEEDBACK"
    )
    EMAIL_ALREADY_REGISTERED = "USER_EMAIL_ALREADY_REGISTERED"
    PLATFORM_ROLE_WRONG_ENDPOINT = "USER_PLATFORM_ROLE_WRONG_ENDPOINT"
    STATUS_WRONG_ENDPOINT = "USER_STATUS_WRONG_ENDPOINT"
    CANNOT_REMOVE_LAST_ADMIN = "USER_CANNOT_REMOVE_LAST_ADMIN"
    CANNOT_DELETE_SELF = "USER_CANNOT_DELETE_SELF"
    OWNER_MUST_BE_GUILD_ADMIN = "OWNER_MUST_BE_GUILD_ADMIN"
    OWNER_ALREADY_HOLDS_CONTENT = "OWNER_ALREADY_HOLDS_CONTENT"
    NOT_IN_GUILD = "USER_NOT_IN_GUILD"
    AVATAR_NOT_FOUND = "USER_AVATAR_NOT_FOUND"
    AVATAR_INVALID_IMAGE = "USER_AVATAR_INVALID_IMAGE"
    AVATAR_TOO_LARGE = "USER_AVATAR_TOO_LARGE"
    AVATAR_NOT_SQUARE = "USER_AVATAR_NOT_SQUARE"
    AVATAR_TOO_LARGE_DIMENSIONS = "USER_AVATAR_TOO_LARGE_DIMENSIONS"
    # A read payload's ``avatar_url`` is a path this API serves; writing one
    # back would store it as though it were an external picture URL.
    AVATAR_URL_NOT_EXTERNAL = "USER_AVATAR_URL_NOT_EXTERNAL"
    #: A decoration this account's library does not answer for — one it does
    #: not have, or one it has for a different slot.
    DECORATION_NOT_OWNED = "USER_DECORATION_NOT_OWNED"
    #: A pack id this build does not ship.
    DECORATION_PACK_NOT_FOUND = "USER_DECORATION_PACK_NOT_FOUND"


class ImportMessages:
    PROJECT_NOT_FOUND = "IMPORT_PROJECT_NOT_FOUND"
    PROJECT_ARCHIVED = "IMPORT_PROJECT_ARCHIVED"
    NO_PERMISSION = "IMPORT_NO_PERMISSION"
    INSUFFICIENT_PERMISSION = "IMPORT_INSUFFICIENT_PERMISSION"
    INVALID_STATUS_ID = "IMPORT_INVALID_STATUS_ID"
    PARSE_FAILED = "IMPORT_PARSE_FAILED"


class ProjectExportMessages:
    SCHEMA_VERSION_UNSUPPORTED = "PROJECT_EXPORT_SCHEMA_VERSION_UNSUPPORTED"
    INVALID_PAYLOAD = "PROJECT_EXPORT_INVALID_PAYLOAD"
    INITIATIVE_NOT_FOUND = "PROJECT_EXPORT_INITIATIVE_NOT_FOUND"
    NO_TASK_STATUSES = "PROJECT_EXPORT_NO_TASK_STATUSES"


class ExportMessages:
    EXPORT_UNKNOWN_SOURCE = "EXPORT_UNKNOWN_SOURCE"
    EXPORT_INVALID_FORMAT = "EXPORT_INVALID_FORMAT"
    EXPORT_INVALID_PARAMS = "EXPORT_INVALID_PARAMS"
    EXPORT_TOO_LARGE = "EXPORT_TOO_LARGE"
    EXPORT_JOB_LIMIT_REACHED = "EXPORT_JOB_LIMIT_REACHED"
    EXPORT_WRITE_REQUIRED = "EXPORT_WRITE_REQUIRED"
    EXPORT_JOB_NOT_FOUND = "EXPORT_JOB_NOT_FOUND"
    EXPORT_NOT_READY = "EXPORT_NOT_READY"
    EXPORT_ADMIN_REQUIRED = "EXPORT_ADMIN_REQUIRED"


class ImportEngineMessages:
    IMPORT_UNKNOWN_TYPE = "IMPORT_UNKNOWN_TYPE"
    IMPORT_INVALID_ENVELOPE = "IMPORT_INVALID_ENVELOPE"
    IMPORT_SCHEMA_VERSION_UNSUPPORTED = "IMPORT_SCHEMA_VERSION_UNSUPPORTED"
    IMPORT_INVALID_PARAMS = "IMPORT_INVALID_PARAMS"
    IMPORT_TOO_LARGE = "IMPORT_TOO_LARGE"
    IMPORT_JOB_LIMIT_REACHED = "IMPORT_JOB_LIMIT_REACHED"
    IMPORT_WRITE_REQUIRED = "IMPORT_WRITE_REQUIRED"
    IMPORT_ADMIN_REQUIRED = "IMPORT_ADMIN_REQUIRED"
    IMPORT_JOB_NOT_FOUND = "IMPORT_JOB_NOT_FOUND"
    IMPORT_NOT_CANCELLABLE = "IMPORT_NOT_CANCELLABLE"
    IMPORT_NOT_CONFIRMABLE = "IMPORT_NOT_CONFIRMABLE"
    IMPORT_ZIP_INVALID = "IMPORT_ZIP_INVALID"
    IMPORT_QUOTA_EXCEEDED = "IMPORT_QUOTA_EXCEEDED"
    IMPORT_ACCESS_REVOKED = "IMPORT_ACCESS_REVOKED"
    IMPORT_INTERRUPTED = "IMPORT_INTERRUPTED"
    IMPORT_APPLY_FAILED = "IMPORT_APPLY_FAILED"
    IMPORT_CREATOR_INACTIVE = "IMPORT_CREATOR_INACTIVE"
    IMPORT_PERMISSION_REQUIRED = "IMPORT_PERMISSION_REQUIRED"
    IMPORT_TOOL_DISABLED = "IMPORT_TOOL_DISABLED"


class QueryMessages:
    INVALID_CONDITIONS = "QUERY_INVALID_CONDITIONS"
    INVALID_SORT_FIELDS = "QUERY_INVALID_SORT_FIELDS"


class NotificationMessages:
    NOT_FOUND = "NOTIFICATION_NOT_FOUND"


class CalendarMessages:
    NOT_FOUND = "CALENDAR_NOT_FOUND"
    CREATE_PERMISSION_REQUIRED = "CALENDAR_CREATE_PERMISSION_REQUIRED"
    FEATURE_DISABLED = "CALENDARS_NOT_ENABLED"
    PERMISSION_REQUIRED = "CALENDAR_PERMISSION_REQUIRED"
    OWNER_REQUIRED = "CALENDAR_OWNER_REQUIRED"
    WRITE_ACCESS_REQUIRED = "CALENDAR_WRITE_ACCESS_REQUIRED"
    GRANT_CANNOT_MANAGE_MEMBERS = "CALENDAR_GRANT_CANNOT_MANAGE_MEMBERS"
    # A guild calendar lives inside the calendar app, which is what reaches it
    # and what its removal takes with it. Without the app there is nowhere to
    # put one.
    GUILD_APP_REQUIRED = "CALENDAR_GUILD_APP_REQUIRED"


class CalendarEventMessages:
    NOT_FOUND = "CALENDAR_EVENT_NOT_FOUND"
    INVALID_ATTENDEE_IDS = "CALENDAR_EVENT_INVALID_ATTENDEE_IDS"
    ICAL_PARSE_FAILED = "ICAL_PARSE_FAILED"
    ICAL_NO_EVENTS = "ICAL_NO_EVENTS_FOUND"
    # A guild calendar holds guild-level content only. Things defined on an
    # initiative — custom properties, documents — have no counterpart at guild
    # scope, so an event there cannot carry them; and an event cannot be moved
    # across the guild/initiative line, because it would take its initiative
    # attachments with it.
    GUILD_CALENDAR_NO_PROPERTIES = "CALENDAR_EVENT_GUILD_CALENDAR_NO_PROPERTIES"
    GUILD_CALENDAR_NO_DOCUMENTS = "CALENDAR_EVENT_GUILD_CALENDAR_NO_DOCUMENTS"
    CANNOT_CROSS_SCOPE = "CALENDAR_EVENT_CANNOT_CROSS_SCOPE"


class DashboardMessages:
    NOT_FOUND = "DASHBOARD_NOT_FOUND"
    CREATE_PERMISSION_REQUIRED = "DASHBOARD_CREATE_PERMISSION_REQUIRED"
    FEATURE_DISABLED = "DASHBOARDS_NOT_ENABLED"
    PERMISSION_REQUIRED = "DASHBOARD_PERMISSION_REQUIRED"
    OWNER_REQUIRED = "DASHBOARD_OWNER_REQUIRED"
    WRITE_ACCESS_REQUIRED = "DASHBOARD_WRITE_ACCESS_REQUIRED"
    GRANT_CANNOT_MANAGE_MEMBERS = "DASHBOARD_GRANT_CANNOT_MANAGE_MEMBERS"
    # Definition / config validation (app.services.tenant.dashboard_definition).
    DEFINITION_INVALID = "DASHBOARD_DEFINITION_INVALID"
    DEFINITION_VERSION_UNSUPPORTED = "DASHBOARD_DEFINITION_VERSION_UNSUPPORTED"
    WIDGET_INVALID = "DASHBOARD_WIDGET_INVALID"
    WIDGET_TYPE_UNKNOWN = "DASHBOARD_WIDGET_TYPE_UNKNOWN"
    WIDGET_ID_DUPLICATE = "DASHBOARD_WIDGET_ID_DUPLICATE"
    WIDGET_OPTION_INVALID = "DASHBOARD_WIDGET_OPTION_INVALID"
    TOO_MANY_WIDGETS = "DASHBOARD_TOO_MANY_WIDGETS"
    BINDING_INVALID = "DASHBOARD_BINDING_INVALID"
    BINDING_SOURCE_UNKNOWN = "DASHBOARD_BINDING_SOURCE_UNKNOWN"
    BINDING_SOURCE_NOT_ALLOWED = "DASHBOARD_BINDING_SOURCE_NOT_ALLOWED"
    CONFIG_INVALID = "DASHBOARD_CONFIG_INVALID"


class MarketplaceMessages:
    LISTING_NOT_FOUND = "MARKETPLACE_LISTING_NOT_FOUND"
    #: The listing exists but nothing about it can be installed here — withdrawn
    #: by its publisher, or its only versions need a newer app.
    LISTING_UNAVAILABLE = "MARKETPLACE_LISTING_UNAVAILABLE"
    LISTING_VERSION_INCOMPATIBLE = "MARKETPLACE_LISTING_VERSION_INCOMPATIBLE"
    #: A dashboard that ships with an app, asked for by a guild that does not
    #: have that app installed. Its tiles draw that app's widgets, so there
    #: would be nothing behind any of them.
    LISTING_NEEDS_APP = "MARKETPLACE_LISTING_NEEDS_APP"
    #: An upgrade was asked for on a dashboard that was authored here, not
    #: installed — there is no listing to re-pin it to.
    NOT_INSTALLED_FROM_LISTING = "MARKETPLACE_NOT_INSTALLED_FROM_LISTING"
    ALREADY_LATEST_VERSION = "MARKETPLACE_ALREADY_LATEST_VERSION"
    MEDIA_NOT_FOUND = "MARKETPLACE_MEDIA_NOT_FOUND"
    #: A rescan was asked for on a deployment that publishes no catalog
    #: directory of its own — nothing to scan until one is configured.
    OPERATOR_CATALOG_NOT_CONFIGURED = "MARKETPLACE_OPERATOR_CATALOG_NOT_CONFIGURED"
    #: The directory is configured but not present — usually a volume that did
    #: not mount, or a path that differs from the one inside the container.
    OPERATOR_CATALOG_DIR_MISSING = "MARKETPLACE_OPERATOR_CATALOG_DIRECTORY_MISSING"
    #: One scan at a time: the answer a second one would give is the one
    #: already being computed.
    OPERATOR_CATALOG_SCAN_RUNNING = "MARKETPLACE_OPERATOR_CATALOG_SCAN_RUNNING"


class MarketplaceRegistryMessages:
    """Outcomes of a signed-registry refresh.

    Every code here either answers an operator's "refresh now" or is recorded
    as the last refusal so the status panel can say why the catalog did not
    move. The refusals are deliberately specific: an operator reading one has
    to be able to tell a misconfigured key from an index their host is serving
    from cache.
    """

    #: No registry URL and key set are configured, or the operator switched
    #: ingestion off. The remote provider is absent rather than broken.
    NOT_CONFIGURED = "MARKETPLACE_REGISTRY_NOT_CONFIGURED"
    #: A refresh is already running; the second caller is told rather than
    #: queued, because both would be fetching the same index.
    REFRESH_IN_PROGRESS = "MARKETPLACE_REGISTRY_REFRESH_IN_PROGRESS"
    #: The configured key set could not be read as a JWKS document.
    KEYS_INVALID = "MARKETPLACE_REGISTRY_KEYS_INVALID"

    #: The index or its signature could not be fetched.
    UNREACHABLE = "MARKETPLACE_REGISTRY_UNREACHABLE"
    #: The index exceeded the size a registry index is allowed to be.
    INDEX_TOO_LARGE = "MARKETPLACE_REGISTRY_INDEX_TOO_LARGE"
    #: The index parsed as JSON but is not shaped like an index.
    INDEX_MALFORMED = "MARKETPLACE_REGISTRY_INDEX_MALFORMED"
    #: The signature does not match the index bytes that were received.
    SIGNATURE_INVALID = "MARKETPLACE_REGISTRY_SIGNATURE_INVALID"
    #: The index was signed by a key this deployment does not trust.
    KEY_UNKNOWN = "MARKETPLACE_REGISTRY_KEY_UNKNOWN"
    #: The index is older than the one already accepted, or reuses its serial
    #: for different content.
    SERIAL_REGRESSION = "MARKETPLACE_REGISTRY_SERIAL_REGRESSION"
    #: The index is outside the freshness window this deployment accepts.
    INDEX_STALE = "MARKETPLACE_REGISTRY_INDEX_STALE"

    #: The signing key is not authorized for that listing's publisher prefix.
    PUBLISHER_NOT_AUTHORIZED = "MARKETPLACE_REGISTRY_PUBLISHER_NOT_AUTHORIZED"
    #: ``core.*`` names listings shipped in this repo and is never published
    #: by a registry.
    RESERVED_NAMESPACE = "MARKETPLACE_REGISTRY_RESERVED_NAMESPACE"
    #: A manifest or image the index named could not be fetched.
    ARTIFACT_UNREACHABLE = "MARKETPLACE_REGISTRY_ARTIFACT_UNREACHABLE"
    #: A manifest or image did not match what the index says it is — digest,
    #: size, type, or the origin it is served from.
    ARTIFACT_INVALID = "MARKETPLACE_REGISTRY_ARTIFACT_INVALID"
    #: The listing itself was refused by the catalog's validator.
    LISTING_REJECTED = "MARKETPLACE_REGISTRY_LISTING_REJECTED"


class QueueMessages:
    NOT_FOUND = "QUEUE_NOT_FOUND"
    ITEM_NOT_FOUND = "QUEUE_ITEM_NOT_FOUND"
    INITIATIVE_NOT_FOUND = "QUEUE_INITIATIVE_NOT_FOUND"
    PERMISSION_REQUIRED = "QUEUE_PERMISSION_REQUIRED"
    CREATE_PERMISSION_REQUIRED = "QUEUE_CREATE_PERMISSION_REQUIRED"
    WRITE_ACCESS_REQUIRED = "QUEUE_WRITE_ACCESS_REQUIRED"
    OWNER_REQUIRED = "QUEUE_OWNER_REQUIRED"
    NOT_ACTIVE = "QUEUE_NOT_ACTIVE"
    ALREADY_ACTIVE = "QUEUE_ALREADY_ACTIVE"
    NO_ITEMS = "QUEUE_NO_ITEMS"
    NO_CURRENT_ITEM = "QUEUE_NO_CURRENT_ITEM"
    ITEM_NOT_HELD = "QUEUE_ITEM_NOT_HELD"
    FEATURE_DISABLED = "QUEUES_NOT_ENABLED"


class CounterMessages:
    NOT_FOUND = "COUNTER_NOT_FOUND"
    GROUP_NOT_FOUND = "COUNTER_GROUP_NOT_FOUND"
    GRANT_CANNOT_MANAGE = "COUNTER_GRANT_CANNOT_MANAGE"
    INITIATIVE_NOT_FOUND = "COUNTER_INITIATIVE_NOT_FOUND"
    PERMISSION_REQUIRED = "COUNTER_PERMISSION_REQUIRED"
    CREATE_PERMISSION_REQUIRED = "COUNTER_CREATE_PERMISSION_REQUIRED"
    WRITE_ACCESS_REQUIRED = "COUNTER_WRITE_ACCESS_REQUIRED"
    OWNER_REQUIRED = "COUNTER_OWNER_REQUIRED"
    FEATURE_DISABLED = "COUNTERS_NOT_ENABLED"
    VIEW_MODE_REQUIRES_BOUNDS = "COUNTER_VIEW_MODE_REQUIRES_BOUNDS"
    MIN_GREATER_THAN_MAX = "COUNTER_MIN_GREATER_THAN_MAX"
    STEP_MUST_BE_POSITIVE = "COUNTER_STEP_MUST_BE_POSITIVE"
    OUT_OF_RANGE = "COUNTER_OUT_OF_RANGE"


class TrashMessages:
    NOT_FOUND = "TRASH_ITEM_NOT_FOUND"
    NEEDS_REASSIGNMENT = "TRASH_NEEDS_REASSIGNMENT"
    INVALID_OWNER = "TRASH_INVALID_OWNER"
    PURGE_REQUIRES_ADMIN = "TRASH_PURGE_REQUIRES_ADMIN"
    UNKNOWN_ENTITY_TYPE = "TRASH_UNKNOWN_ENTITY_TYPE"


class GuildAppMessages:
    NOT_FOUND = "GUILD_APP_NOT_FOUND"
    ADMIN_REQUIRED = "GUILD_APP_ADMIN_REQUIRED"
    #: The listing named is not an app, or names an app kind this build cannot
    #: install.
    NOT_AN_APP = "GUILD_APP_LISTING_NOT_AN_APP"
    #: This guild already has this listing installed. Apps mount one guild-wide
    #: surface each, so a second copy has nothing to be.
    ALREADY_INSTALLED = "GUILD_APP_ALREADY_INSTALLED"
    #: A valid app of a kind this build does not mount into a guild yet — see
    #: GUILD_INSTALLABLE_APP_KINDS. Publishable and browsable, not installable
    #: here, and told so by name rather than half-mounted.
    KIND_NOT_INSTALLABLE = "GUILD_APP_KIND_NOT_INSTALLABLE"

    # --- configuration ---
    #: The request named a connection the pinned definition does not declare.
    CONFIG_UNKNOWN_CONNECTION = "GUILD_APP_CONFIG_UNKNOWN_CONNECTION"
    #: The request named a field that connection does not declare.
    CONFIG_UNKNOWN_FIELD = "GUILD_APP_CONFIG_UNKNOWN_FIELD"
    #: A value that does not match its declared type, or an empty one.
    CONFIG_INVALID_VALUE = "GUILD_APP_CONFIG_INVALID_VALUE"
    #: A value longer than this build stores for that field.
    CONFIG_VALUE_TOO_LONG = "GUILD_APP_CONFIG_VALUE_TOO_LONG"
    #: A required field left without a value.
    CONFIG_REQUIRED_FIELD = "GUILD_APP_CONFIG_REQUIRED_FIELD"
    #: A field the app writes back itself when it completes a vendor flow; the
    #: settings form is not where it is set.
    CONFIG_MANAGED_FIELD = "GUILD_APP_CONFIG_MANAGED_FIELD"

    # --- connections ---
    #: No such connection on this install, or no such member connection.
    CONNECTION_NOT_FOUND = "GUILD_APP_CONNECTION_NOT_FOUND"
    #: Connecting runs a vendor's flow, and this connection declares none —
    #: its values are typed into the settings form instead. Named for the
    #: scope because that is what it meant when only one scope could have a
    #: flow; a guild-wide connection may now have one too.
    CONNECTION_NOT_INTERACTIVE = "GUILD_APP_CONNECTION_NOT_INTERACTIVE"
    #: Guild-wide values are configured through the config endpoint; a
    #: per-member connection is not.
    CONNECTION_NOT_STATIC = "GUILD_APP_CONNECTION_NOT_STATIC"
    #: A guild admin has stopped this member connecting this one.
    CONNECTION_BLOCKED = "GUILD_APP_CONNECTION_BLOCKED"
    #: The app is installed but turned off, so nothing flows through it.
    DISABLED = "GUILD_APP_DISABLED"

    # --- acting as a member ---
    #: This app never acts as anybody, so there is nothing for a member to
    #: authorize.
    DELEGATION_NOT_OFFERED = "GUILD_APP_DELEGATION_NOT_OFFERED"
    #: No authorization from this member for this app.
    DELEGATION_NOT_FOUND = "GUILD_APP_DELEGATION_NOT_FOUND"

    # --- apps the deployment provides ---
    #: The deployment installs this app in every guild and a guild admin does
    #: not remove or disable it. The affordances are absent rather than
    #: erroring; this answers a request that arrives anyway.
    MANDATORY = "GUILD_APP_MANDATORY"

    # --- service apps ---
    #: This install's app service is not wired up here — never registered, or
    #: the operator turned the registration off. Nothing this app offers can be
    #: reached until that changes.
    SERVICE_NOT_REGISTERED = "GUILD_APP_SERVICE_NOT_REGISTERED"
    #: The pinned definition declares no surface under that id.
    SURFACE_NOT_FOUND = "GUILD_APP_SURFACE_NOT_FOUND"
    #: The surface names an audience the caller is not in — declared for the
    #: guild's admins, or for an initiative's managers where the caller manages
    #: nothing.
    SURFACE_ADMIN_ONLY = "GUILD_APP_SURFACE_ADMIN_ONLY"
    #: The placement sent is not a shape this build stores, or it names an
    #: initiative that is not one of this guild's.
    PLACEMENT_INVALID = "GUILD_APP_PLACEMENT_INVALID"


class AppServiceMessages:
    """Codes for the deployment-level app service registry.

    Read by an operator wiring an app up, so each code names the step that
    refused rather than a generic failure.
    """

    NOT_FOUND = "APP_SERVICE_NOT_FOUND"
    #: Another registration already carries this public_id.
    DUPLICATE_PUBLIC_ID = "APP_SERVICE_DUPLICATE_PUBLIC_ID"
    #: public_id, base_url, an origin, or a version string this build refuses.
    INVALID_PUBLIC_ID = "APP_SERVICE_INVALID_PUBLIC_ID"
    INVALID_BASE_URL = "APP_SERVICE_INVALID_BASE_URL"
    #: The browser-facing base, when an app answers there rather than at the
    #: address Initiative's own server calls.
    INVALID_EMBED_ORIGIN = "APP_SERVICE_INVALID_EMBED_ORIGIN"
    INVALID_ORIGIN = "APP_SERVICE_INVALID_ORIGIN"
    #: A grant outside the closed operator-conferred vocabulary.
    UNKNOWN_GRANT = "APP_SERVICE_UNKNOWN_GRANT"
    #: The delegation key set is not a JWKS this build can verify against, or
    #: an entry in it carries no ``kid`` for a token to name.
    INVALID_DELEGATION_JWKS = "APP_SERVICE_INVALID_DELEGATION_JWKS"
    #: A registration with no stored secret cannot complete a handshake.
    SECRET_REQUIRED = "APP_SERVICE_SECRET_REQUIRED"
    #: The APP_PLATFORM_* signing keypair is not configured. It is required and
    #: has no fallback, so registration and verification fail closed until an
    #: operator supplies one.
    SIGNING_NOT_CONFIGURED = "APP_SERVICE_SIGNING_NOT_CONFIGURED"
    #: The service could not be reached, or did not answer with a manifest.
    UNREACHABLE = "APP_SERVICE_UNREACHABLE"
    #: The manifest was served but this build will not accept it (unknown
    #: protocol version, missing fields, or a definition the validator refuses).
    INVALID_MANIFEST = "APP_SERVICE_INVALID_MANIFEST"
    #: The served manifest no longer hashes to the one recorded at registration.
    MANIFEST_CHANGED = "APP_SERVICE_MANIFEST_CHANGED"
    #: The manifest names a different app than the registration does.
    PUBLIC_ID_MISMATCH = "APP_SERVICE_PUBLIC_ID_MISMATCH"
    #: The challenge came back signed with a different secret.
    SIGNATURE_MISMATCH = "APP_SERVICE_SIGNATURE_MISMATCH"


class AppDataMessages:
    """Codes for the widget data proxy.

    Read by a member looking at a dashboard, so each one distinguishes a state
    they can act on (connect an account, ask an admin to configure the app) from
    one they can only wait out (the app is unreachable).
    """

    #: The install names no such data source, or the pinned definition is not a
    #: service app's at all.
    ENDPOINT_NOT_FOUND = "APP_DATA_ENDPOINT_NOT_FOUND"
    #: The source is declared for guild admins and the caller is a member.
    ADMIN_ONLY = "APP_DATA_ADMIN_ONLY"
    #: The source declares no such parameter, so there is nothing to fill in.
    PARAM_NOT_FOUND = "APP_DATA_PARAM_NOT_FOUND"
    #: The install is turned off in this guild.
    APP_DISABLED = "APP_DATA_APP_DISABLED"
    #: No registration wires this app up on this deployment.
    SERVICE_NOT_REGISTERED = "APP_DATA_SERVICE_NOT_REGISTERED"
    #: The operator's kill switch is off, or the registration has not verified.
    SERVICE_DISABLED = "APP_DATA_SERVICE_DISABLED"
    #: A parameter the source does not declare, or a value that does not match
    #: its declared type.
    INVALID_PARAMS = "APP_DATA_INVALID_PARAMS"
    #: A guild-scoped credential this source needs has not been supplied.
    NEEDS_CONFIGURATION = "APP_DATA_NEEDS_CONFIGURATION"
    #: The source reads the member's own vendor account and they have not
    #: connected it yet.
    CONNECTION_REQUIRED = "APP_DATA_CONNECTION_REQUIRED"
    #: The app could not be reached, timed out, or answered with something that
    #: is not a data response.
    SERVICE_UNAVAILABLE = "APP_SERVICE_UNAVAILABLE"
    #: The app answered past the response ceiling.
    RESPONSE_TOO_LARGE = "APP_DATA_RESPONSE_TOO_LARGE"
    #: This worker already has as many calls in flight to this app as it will
    #: hold open, so one slow app cannot consume the pool.
    BUSY = "APP_DATA_BUSY"
    #: Reserved for the platform-wide limiter, which spans containers and
    #: arrives with the rate-limiting workstream.
    RATE_LIMITED = "APP_DATA_RATE_LIMITED"


class AppChannelMessages:
    """Codes for the channels an app service calls back into Initiative on.

    Read by an app author rather than by a person in the UI, so each names the
    step that refused: an envelope this build will not accept, an install this
    caller does not own, or a payload outside what the pinned manifest declared.
    """

    # --- the signed envelope ---
    #: A required signing header is absent or unusably shaped.
    MISSING_SIGNATURE = "APP_CHANNEL_MISSING_SIGNATURE"
    #: The signed timestamp sits outside the freshness window.
    STALE_TIMESTAMP = "APP_CHANNEL_STALE_TIMESTAMP"
    #: No registration answers to the app id the request named.
    UNKNOWN_APP = "APP_CHANNEL_UNKNOWN_APP"
    #: The signature does not match what this registration's secret produces.
    INVALID_SIGNATURE = "APP_CHANNEL_INVALID_SIGNATURE"
    #: This nonce was already spent, so the request has been seen before.
    REPLAYED_REQUEST = "APP_CHANNEL_REPLAYED_REQUEST"
    #: The operator turned this registration off; every channel it backs stops.
    APP_DISABLED = "APP_CHANNEL_APP_DISABLED"

    # --- the install being addressed ---
    #: No install of this app in that guild — never installed, uninstalled, or
    #: the guild is not one this caller may see.
    INSTALL_NOT_FOUND = "APP_CHANNEL_INSTALL_NOT_FOUND"
    #: The install exists but the guild turned it off.
    INSTALL_DISABLED = "APP_CHANNEL_INSTALL_DISABLED"
    #: The guild is frozen, so this channel accepts no writes into it.
    GUILD_READ_ONLY = "APP_CHANNEL_GUILD_READ_ONLY"
    #: No connection on this install answers to that reference.
    CONNECTION_NOT_FOUND = "APP_CHANNEL_CONNECTION_NOT_FOUND"
    #: A guild admin stopped this member's connection; the app may not revive it.
    CONNECTION_BLOCKED = "APP_CHANNEL_CONNECTION_BLOCKED"
    #: This install declares more than one per-member connection, and the
    #: request did not say which of them it meant.
    CONNECTION_UNSPECIFIED = "APP_CHANNEL_CONNECTION_UNSPECIFIED"

    # --- what the app sent ---
    #: The body is not the JSON object this channel expects.
    INVALID_PAYLOAD = "APP_CHANNEL_INVALID_PAYLOAD"
    #: An event type the pinned definition does not declare, or one namespaced
    #: under an app other than the caller.
    UNKNOWN_EVENT_TYPE = "APP_CHANNEL_UNKNOWN_EVENT_TYPE"
    #: The event body is larger than this build will carry.
    EVENT_TOO_LARGE = "APP_CHANNEL_EVENT_TOO_LARGE"
    #: A config state outside what an app may report.
    INVALID_CONFIG_STATE = "APP_CHANNEL_INVALID_CONFIG_STATE"


class WebhookSubscriptionMessages:
    INVALID_TARGET_URL = "WEBHOOK_INVALID_TARGET_URL"
    PRIVATE_TARGET_URL = "WEBHOOK_PRIVATE_TARGET_URL"
    NOT_FOUND = "WEBHOOK_SUBSCRIPTION_NOT_FOUND"
    UNKNOWN_EVENT_TYPE = "WEBHOOK_UNKNOWN_EVENT_TYPE"
    UNKNOWN_FIELD = "WEBHOOK_UNKNOWN_FIELD"


class AIMessages:
    INVALID_BASE_URL = "AI_INVALID_BASE_URL"
    PROVIDER_NOT_ALLOWED = "AI_PROVIDER_NOT_ALLOWED"
    CONNECTION_NOT_FOUND = "AI_CONNECTION_NOT_FOUND"
    MEMBER_KEYS_DISABLED = "AI_MEMBER_KEYS_DISABLED"
    INVALID_API_KEY = "AI_INVALID_API_KEY"


class NativeMessages:
    OTA_BUNDLE_NOT_AVAILABLE = "NATIVE_OTA_BUNDLE_NOT_AVAILABLE"


class BillingMessages:
    """Codes for the service-to-service billing write boundary.

    These endpoints are machine-to-machine (the billing service, not the
    SPA), so the codes are consumed by the caller's logs/retry logic rather
    than errors.json.
    """

    NOT_CONFIGURED = "BILLING_NOT_CONFIGURED"
    #: The configured verifying key could not be read. A deployment fault
    #: rather than a caller fault, so it answers alongside NOT_CONFIGURED.
    KEY_UNREADABLE = "BILLING_KEY_UNREADABLE"
    MISSING_SIGNATURE = "BILLING_MISSING_SIGNATURE"
    STALE_TIMESTAMP = "BILLING_STALE_TIMESTAMP"
    INVALID_SIGNATURE = "BILLING_INVALID_SIGNATURE"
    INVALID_TOKEN = "BILLING_INVALID_TOKEN"
    REPLAYED_TOKEN = "BILLING_REPLAYED_TOKEN"
    INVALID_PAYLOAD = "BILLING_INVALID_PAYLOAD"
    GUILD_NOT_FOUND = "BILLING_GUILD_NOT_FOUND"
    SUPPORT_SOURCE_RESTRICTED = "BILLING_SUPPORT_SOURCE_RESTRICTED"
    SUPPORT_CANNOT_LOWER = "BILLING_SUPPORT_CANNOT_LOWER"
    ACTOR_REQUIRED = "BILLING_ACTOR_REQUIRED"
    PORTAL_NOT_CONFIGURED = "BILLING_PORTAL_NOT_CONFIGURED"
    PORTAL_SIGNING_NOT_CONFIGURED = "BILLING_PORTAL_SIGNING_NOT_CONFIGURED"
    PORTAL_GRANT_UNAVAILABLE = "BILLING_PORTAL_GRANT_UNAVAILABLE"
