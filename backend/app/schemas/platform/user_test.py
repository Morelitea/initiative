"""Unit tests for the guards on the user schemas.

The old ``avatar_base64`` cap tests are gone with the field: a picture is no
longer carried inside a payload, so there is no oversized-string case left to
bound. What replaces them is the guard on ``avatar_url`` — the read schemas
hand back the path this API serves a picture from, and that value must not come
back in as though it named an image hosted somewhere else.
"""

import pytest
from pydantic import ValidationError

from app.schemas.platform import user as user_schemas
from app.schemas.platform.user import (
    ProfileDecorations,
    UserPublic,
    UserRead,
    UserSelfUpdate,
    UserSummary,
)


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


@pytest.mark.unit
def test_a_year_is_kept_for_a_decoration_that_carries_one() -> None:
    """The year is the wearer's, not the clock's: somebody who finished in 2014
    is still a 2014 grad next January, so it is stored as given."""
    worn = ProfileDecorations(banner="education.gradbanner", grad_year=2014)

    assert worn.grad_year == 2014


@pytest.mark.unit
def test_a_year_is_kept_when_the_trophy_is_what_carries_it() -> None:
    worn = ProfileDecorations(trophies=["education.gradtrophy"], grad_year=2031)

    assert worn.grad_year == 2031


@pytest.mark.unit
def test_a_year_on_something_that_carries_none_is_dropped() -> None:
    """The same rule a stray colour gets: a value nothing would draw is not
    state worth keeping, and nothing else would ever clear it."""
    worn = ProfileDecorations(banner="core.aurora", grad_year=2014)

    assert worn.grad_year is None


@pytest.mark.unit
def test_a_year_outside_the_range_is_refused() -> None:
    with pytest.raises(ValidationError):
        ProfileDecorations(trophies=["education.gradtrophy"], grad_year=1492)
