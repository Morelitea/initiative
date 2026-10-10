"""The demo's manifest, and the secret file beside it.

The manifest is public: the personas every bundle names, the shapes a pitch
can be made from, the communities the demo is seeded with and the fixed
accounts seated in them. How to sign in as a fixed account is not, so its
address and password come from a second file, keyed by handle.

Paths in the manifest are relative to the manifest file.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field, RootModel, SecretStr
from pydantic import model_validator

from app.core import usernames
from app.models.platform.guild import MEMBER_DISPLAY_NAME_MAX_LENGTH
from app.models.platform.guild import CommunityCategory, CommunityRole
from app.models.platform.user import UserRole
from app.models.tenant.initiative import InitiativeJoinPolicy


def split_handle(handle: str) -> tuple[str, int]:
    """``bea#0042`` as its name part and its number."""
    name, _, number = handle.partition("#")
    return name, int(number)


def _handle(value: str) -> str:
    name, digits = usernames.parse_handle(value)
    if digits is None or len(digits) != usernames.DISCRIMINATOR_DIGITS:
        raise ValueError("a handle is a name, '#', and four digits")
    return usernames.format_handle(usernames.validate(name), int(digits))


#: A whole handle, ``name#1234``, normalized as the users table compares it.
Handle = Annotated[str, AfterValidator(_handle)]


class Persona(BaseModel):
    """Somebody the bundles name. Nobody signs in as one."""

    handle: Handle
    #: What the persona is called in every community it is seated in.
    display_name: str = Field(min_length=1, max_length=MEMBER_DISPLAY_NAME_MAX_LENGTH)
    #: Text the persona's picture is drawn from; none leaves it without one.
    avatar_seed: str | None = None


#: What a shape's key is written in. It names the shape's stored bundle.
_KEY_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")


def _key(value: str) -> str:
    if not value or not set(value) <= _KEY_CHARACTERS:
        raise ValueError("a shape key is lowercase letters, digits and hyphens")
    return value


class Shape(BaseModel):
    """A bundle a pitch can be made from."""

    key: Annotated[str, AfterValidator(_key)]
    label: str = Field(min_length=1)
    bundle: str


class DirectoryCard(BaseModel):
    """How a listed community shows in the directory."""

    categories: list[CommunityCategory] = Field(min_length=1)
    #: How a member who joined from the card comes into its initiatives.
    join_policy: InitiativeJoinPolicy = InitiativeJoinPolicy.open


class Community(BaseModel):
    """A community the demo is seeded with, made from one bundle."""

    name: str = Field(min_length=1)
    #: An image file for the community's icon.
    icon: str | None = None
    #: The persona that creates it and holds its seat. No persona creates two,
    #: which is how a later run finds the community again.
    creator: Handle
    members: list[Handle] = []
    bundle: str
    #: Listed in the directory with this card; unlisted without one.
    directory: DirectoryCard | None = None
    #: Left as it is by ``--rebuild``.
    keep: bool = False


class FixedAccount(BaseModel):
    """An account people sign in to: app review, pen testing, sales."""

    handle: Handle
    tier: UserRole = UserRole.member
    #: Its role in each fixed community, by the community's key.
    communities: dict[str, CommunityRole] = {}
    #: Made an admin of every pitch.
    pitch_editor: bool = False


class DemoManifest(BaseModel):
    personas: list[Persona] = []
    shapes: list[Shape] = []
    #: The background and listed communities.
    communities: list[Community] = []
    #: The communities fixed accounts are seated in, by key.
    fixed_communities: dict[str, Community] = {}
    accounts: list[FixedAccount] = []

    def all_communities(self) -> list[Community]:
        return [*self.communities, *self.fixed_communities.values()]

    @model_validator(mode="after")
    def _consistent(self) -> DemoManifest:
        personas = [p.handle for p in self.personas]
        accounts = [a.handle for a in self.accounts]
        if len(set(personas + accounts)) != len(personas) + len(accounts):
            raise ValueError("every persona and account has a handle of its own")
        if len({s.key for s in self.shapes}) != len(self.shapes):
            raise ValueError("every shape has a key of its own")
        creators = [c.creator for c in self.all_communities()]
        if len(set(creators)) != len(creators):
            raise ValueError("no persona creates two communities")
        for community in self.all_communities():
            if not {community.creator, *community.members} <= set(personas):
                raise ValueError(f"{community.name} names somebody who is no persona")
        for account in self.accounts:
            if not account.communities.keys() <= self.fixed_communities.keys():
                raise ValueError(f"{account.handle} names no fixed community")
            if CommunityRole.support in account.communities.values():
                raise ValueError("support is a grant, not a membership")
        return self


class SignIn(BaseModel):
    address: EmailStr
    password: SecretStr


class SignInFile(RootModel[dict[Handle, SignIn]]):
    """The fixed accounts' sign-in details, by handle."""
