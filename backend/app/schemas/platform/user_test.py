"""Unit tests for the avatar half of the user schemas.

The old ``avatar_base64`` cap tests are gone with the field: a picture is no
longer carried inside a payload, so there is no oversized-string case left to
bound. What replaces them is the guard on ``avatar_url`` — the read schemas
hand back the path this API serves a picture from, and that value must not come
back in as though it named an image hosted somewhere else.
"""

import pytest

from app.schemas.platform import user as user_schemas
from app.schemas.platform.user import UserPublic, UserRead, UserSelfUpdate, UserSummary


@pytest.mark.unit
def test_self_update_accepts_an_external_avatar_url() -> None:
    model = UserSelfUpdate(avatar_url="https://idp.example/pic.png")

    assert model.avatar_url == "https://idp.example/pic.png"


@pytest.mark.unit
def test_self_update_accepts_clearing_the_avatar_url() -> None:
    assert UserSelfUpdate(avatar_url=None).avatar_url is None


@pytest.mark.unit
@pytest.mark.parametrize("schema", [UserPublic, UserSummary, UserRead, UserSelfUpdate])
def test_no_schema_carries_the_image_itself(schema) -> None:
    """The picture travels as a URL now; nothing should reintroduce the blob."""
    assert "avatar_base64" not in schema.model_fields
    assert "avatar_url" in schema.model_fields


@pytest.mark.unit
def test_there_is_no_schema_for_editing_another_account() -> None:
    """A guild admin manages membership, not the person.

    ``UserUpdate`` backed a guild-scoped PATCH that could set a co-member's
    name and password; both are properties of an account that spans every guild
    it belongs to. The schema is gone along with the endpoint, so its absence is
    the assertion.
    """
    assert not hasattr(user_schemas, "UserUpdate")
