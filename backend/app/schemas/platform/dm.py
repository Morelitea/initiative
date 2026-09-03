"""Payloads for who may ask to message an account.

The policy and its per-community toggles are one screen and travel as one
object, so a write carries whichever halves changed and the pair stays in a
state the screen can render.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import ConfigDict

from app.models.platform.user import Presence, UserStatus
from app.models.platform.user_dm_settings import DmPolicy
from app.schemas.base import SanitizedBaseModel


class CommunityDmToggle(SanitizedBaseModel):
    """One of the reader's communities, and whether it counts.

    Only consulted while the policy is ``community``; the list is returned
    whatever the policy is, so switching to it does not arrive on an empty
    screen.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    guild_id: int
    name: str
    icon_url: Optional[str] = None
    enabled: bool


class DirectMessageSettingsRead(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    dm_policy: DmPolicy
    #: In the reader's own rail order, the same rule My Contacts uses.
    communities: List[CommunityDmToggle]
    #: NULL while the account has not answered the age question, which holds
    #: the policy at ``private`` whatever it says.
    age_confirmed_at: Optional[datetime] = None


class CommunityDmToggleUpdate(SanitizedBaseModel):
    guild_id: int
    enabled: bool


class DirectMessageSettingsUpdate(SanitizedBaseModel):
    """Both halves optional, and omitting one leaves it alone.

    A toggle list is a set of changes rather than the whole list: a client that
    knows about three communities should not be able to silently switch on a
    fourth it has never rendered.
    """

    dm_policy: Optional[DmPolicy] = None
    communities: Optional[List[CommunityDmToggleUpdate]] = None


class IgnoredAccountRead(SanitizedBaseModel):
    """One row of the holder's own list."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    user_id: int
    username: str
    discriminator: int
    avatar_url: Optional[str] = None
    created_at: datetime


class IgnoredAccountsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[IgnoredAccountRead]
    total: int


class DirectMessagePermissionRead(SanitizedBaseModel):
    """What this reader may do about that account, right now.

    ``denied`` covers every refusal with no distinguishing field: a policy that
    does not admit them, an account that cannot be reached, and being ignored
    all answer the same way.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    permission: str


class ContactGrantRead(SanitizedBaseModel):
    """One connection or message request, from the reader's side of it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    user_id: int
    username: str
    discriminator: int
    avatar_url: Optional[str] = None
    #: Carried so a grant renders as an ordinary contact row wherever one is
    #: listed. No ``full_name``: a real name is a per-guild disclosure, and a
    #: grant may name somebody the reader shares no community with.
    status: UserStatus = UserStatus.active
    presence: Presence = Presence.offline
    state: str
    #: True when the reader is the one who asked, which is what tells a
    #: cancellable request from one waiting on them.
    outgoing: bool
    created_at: datetime
    responded_at: Optional[datetime] = None


class ContactGrantsResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    accepted: List[ContactGrantRead]
    incoming: List[ContactGrantRead]
    outgoing: List[ContactGrantRead]


class ConnectionRequestCreate(SanitizedBaseModel):
    """A connection is addressed by handle, never by id.

    One shape whatever the target's policy, and the shape the app-wide people
    search will use: an account on ``private`` is reached by somebody typing
    its handle rather than by being offered from a list.
    """

    username: str
    discriminator: int


class MessageRequestCreate(SanitizedBaseModel):
    """A message request is addressed by id: everyone you may ask is somebody
    you can already see."""

    user_id: int
