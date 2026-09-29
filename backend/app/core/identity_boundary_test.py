"""The two identity types, with and without an installed app's boundary.

For a person both are ``int``, schema and all. Under an install's boundary
they read references in its input phase, stay ``int`` in its handler phase,
and write markers (or the community's known reference) in its response phase.
"""

from __future__ import annotations

from typing import Optional

import pytest
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError

from app.core.identity_boundary import (
    UNKNOWN_REFERENCE_ERROR,
    BoundaryPhase,
    GuildId,
    InstallBoundary,
    PersonId,
    admit_install,
    boundary_scope,
    current_install_boundary,
)
from app.core.messages import AppMessages
from app.db.guild_standing import named_ref_candidates
from app.models.platform.identity_ref import IdentityEntity
from app.schemas.platform.user import AppMemberRead, UserPublic
from app.services.platform.user_avatars import avatar_url


_GUILD = 7
_INSTALL = 3
_PERSON_REF = "uapp_person-one"
_OTHER_REF = "uapp_person-two"
_GUILD_REF = "gapp_the-community"


class _Payload(BaseModel):
    guild_id: GuildId
    owner: PersonId
    helpers: list[PersonId] = []
    reviewer: Optional[PersonId] = None


class _Plain(BaseModel):
    guild_id: int
    owner: int
    helpers: list[int] = []
    reviewer: Optional[int] = None


def _boundary(**overrides) -> InstallBoundary:
    values = {
        "guild_id": _GUILD,
        "install_id": _INSTALL,
        "guild_ref": _GUILD_REF,
        "named": {
            _PERSON_REF: (IdentityEntity.user, 11),
            _OTHER_REF: (IdentityEntity.user, 12),
            _GUILD_REF: (IdentityEntity.guild, _GUILD),
        },
    }
    values.update(overrides)
    return InstallBoundary(**values)


def _errors(exc: ValidationError) -> list[tuple[str, str]]:
    return [(e["type"], e["msg"]) for e in exc.errors()]


# ---------------------------------------------------------------------------
# A person
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["validation", "serialization"])
def test_the_published_schema_is_an_integer(mode):
    ours = _Payload.model_json_schema(mode=mode)
    plain = _Plain.model_json_schema(mode=mode)
    ours.pop("title")
    plain.pop("title")
    assert ours == plain


def test_a_person_reads_and_writes_integers():
    payload = _Payload.model_validate(
        {"guild_id": 7, "owner": "11", "helpers": [12], "reviewer": None}
    )
    assert payload.owner == 11
    assert payload.model_dump(mode="json") == {
        "guild_id": 7,
        "owner": 11,
        "helpers": [12],
        "reviewer": None,
    }


def test_an_open_slot_without_an_install_is_a_person():
    with boundary_scope():
        assert current_install_boundary() is None
        payload = _Payload(guild_id=7, owner=11)
        assert payload.model_dump(mode="json")["owner"] == 11


def test_an_install_is_admitted_only_inside_a_slot():
    with pytest.raises(RuntimeError):
        admit_install(_boundary())


# ---------------------------------------------------------------------------
# An install's input
# ---------------------------------------------------------------------------


def test_references_resolve_to_the_rows_they_name():
    with boundary_scope():
        admit_install(_boundary())
        payload = _Payload.model_validate(
            {
                "guild_id": _GUILD_REF,
                "owner": _PERSON_REF,
                "helpers": [_OTHER_REF, _PERSON_REF],
                "reviewer": _OTHER_REF,
            }
        )
    assert (payload.guild_id, payload.owner, payload.helpers, payload.reviewer) == (
        _GUILD,
        11,
        [12, 11],
        12,
    )


@pytest.mark.parametrize(
    "field, value",
    [
        ("owner", 11),
        ("owner", "11"),
        ("owner", "uapp_nobody-here"),
        ("owner", _GUILD_REF),
        ("guild_id", _GUILD),
        ("guild_id", _PERSON_REF),
    ],
)
def test_anything_but_a_resolved_reference_is_refused(field, value):
    body = {"guild_id": _GUILD_REF, "owner": _PERSON_REF}
    body[field] = value
    with boundary_scope():
        admit_install(_boundary())
        with pytest.raises(ValidationError) as caught:
            _Payload.model_validate(body)
    assert _errors(caught.value) == [
        (UNKNOWN_REFERENCE_ERROR, AppMessages.REFERENCE_UNKNOWN)
    ]


def test_a_community_reference_names_only_the_routed_community():
    named = {_GUILD_REF: (IdentityEntity.guild, _GUILD + 1)}
    with boundary_scope():
        admit_install(_boundary(named=named))
        with pytest.raises(ValidationError):
            _Payload.model_validate({"guild_id": _GUILD_REF, "owner": 1})


# ---------------------------------------------------------------------------
# An install's handler and response
# ---------------------------------------------------------------------------


def test_the_handler_works_in_row_ids():
    with boundary_scope():
        boundary = _boundary()
        admit_install(boundary)
        boundary.phase = BoundaryPhase.handler
        payload = _Payload.model_validate({"guild_id": _GUILD, "owner": 11})
        assert payload.model_dump(mode="json")["owner"] == 11
        assert boundary.wanted == set()


def test_the_response_carries_markers_and_the_known_community_reference():
    with boundary_scope():
        boundary = _boundary()
        admit_install(boundary)
        boundary.phase = BoundaryPhase.response
        dumped = _Payload(guild_id=_GUILD, owner=11, helpers=[12]).model_dump(
            mode="json"
        )
    assert dumped["guild_id"] == _GUILD_REF
    assert dumped["owner"] == f"{boundary.nonce}:u:11"
    assert dumped["helpers"] == [f"{boundary.nonce}:u:12"]
    assert dumped["reviewer"] is None
    assert boundary.wanted == {(IdentityEntity.user, 11), (IdentityEntity.user, 12)}


def test_an_unnamed_community_is_marked_for_minting():
    with boundary_scope():
        boundary = _boundary(guild_ref=None)
        admit_install(boundary)
        boundary.phase = BoundaryPhase.response
        dumped = _Payload(guild_id=_GUILD, owner=11).model_dump(mode="json")
    assert dumped["guild_id"] == f"{boundary.nonce}:g:{_GUILD}"
    assert (IdentityEntity.guild, _GUILD) in boundary.wanted


def test_a_response_names_no_other_community():
    with boundary_scope():
        boundary = _boundary(guild_ref=None)
        admit_install(boundary)
        boundary.phase = BoundaryPhase.response
        with pytest.raises(PydanticSerializationError):
            _Payload(guild_id=_GUILD + 1, owner=11).model_dump(mode="json")


def test_each_request_has_its_own_nonce():
    assert _boundary().nonce != _boundary().nonce


def test_the_slot_closes_with_the_request():
    with boundary_scope():
        admit_install(_boundary())
        assert current_install_boundary() is not None
    assert current_install_boundary() is None


# ---------------------------------------------------------------------------
# What the standing statement is asked about
# ---------------------------------------------------------------------------


def test_only_app_references_are_candidates():
    assert named_ref_candidates(
        [
            _PERSON_REF,
            _PERSON_REF,
            _GUILD_REF,
            "ubil_billing-person",
            "ucli_session-subject",
            "uapp_" + "x" * 80,
            "plain text",
            "42",
        ]
    ) == sorted({_PERSON_REF, _GUILD_REF})


# ---------------------------------------------------------------------------
# members:read
# ---------------------------------------------------------------------------


def test_a_member_for_an_install_is_a_reference_a_handle_a_name_and_a_picture():
    public = UserPublic(
        id=11,
        username="ada",
        discriminator=1234,
        full_name="Ada Lovelace",
        avatar_url="https://pictures.example/ada.png",
    )
    member = AppMemberRead.from_public(public)
    assert set(AppMemberRead.model_fields) == {
        "id",
        "username",
        "discriminator",
        "full_name",
        "avatar_url",
    }
    assert member.avatar_url == "https://pictures.example/ada.png"
    with boundary_scope():
        boundary = _boundary()
        admit_install(boundary)
        boundary.phase = BoundaryPhase.response
        dumped = member.model_dump(mode="json")
    assert dumped["id"] == f"{boundary.nonce}:u:11"
    assert "email" not in dumped


def test_a_picture_this_api_serves_is_not_passed_to_an_install():
    public = UserPublic(
        id=11, username="ada", discriminator=1234, avatar_url=avatar_url(11, "ab" * 32)
    )
    assert AppMemberRead.from_public(public).avatar_url is None
