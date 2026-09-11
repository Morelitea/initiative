"""Tests for reading an IdP's account of an authentication.

Pins the two halves: what a verified id_token's ``amr``/``acr``/``auth_time``
become, and how one provider's entry folds into a session that may already
carry several.
"""

from __future__ import annotations

import pytest

from app.services.auth.assurance import (
    MAX_AMR_VALUE_LENGTH,
    MAX_AMR_VALUES,
    MAX_TRACKED_PROVIDERS,
    ProviderAssurance,
    read_assurance,
    record_for_provider,
    session_amr,
)

pytestmark = [pytest.mark.unit, pytest.mark.auth]


def test_an_idp_that_describes_its_authentication_is_taken_at_its_word():
    assurance = read_assurance(
        {
            "sub": "s",
            "amr": ["pwd", "mfa", "otp"],
            "acr": "phr",
            "auth_time": 1757600000,
        }
    )
    assert assurance.amr == ("pwd", "mfa", "otp")
    assert assurance.acr == "phr"
    assert assurance.auth_time == 1757600000
    assert assurance.as_record() == {
        "auth_time": 1757600000,
        "amr": ["pwd", "mfa", "otp"],
        "acr": "phr",
    }


def test_an_idp_that_says_nothing_records_nothing():
    assurance = read_assurance({"sub": "s", "email": "a@example.com"})
    assert assurance == ProviderAssurance()
    assert assurance.as_record() == {}


@pytest.mark.parametrize(
    "claims",
    [
        {"amr": "mfa"},
        {"amr": {"0": "mfa"}},
        {"amr": [1, None, True]},
        {"amr": ["", "   "]},
        {"amr": ["x" * (MAX_AMR_VALUE_LENGTH + 1)]},
    ],
)
def test_an_amr_in_a_shape_oidc_does_not_describe_is_dropped(claims):
    assert read_assurance(claims).amr == ()


def test_amr_values_are_trimmed_deduplicated_and_bounded():
    claims = {"amr": [" pwd ", "pwd", *[f"m{i}" for i in range(MAX_AMR_VALUES + 5)]]}
    amr = read_assurance(claims).amr
    assert amr[0] == "pwd"
    assert len(amr) == MAX_AMR_VALUES
    assert len(set(amr)) == len(amr)


@pytest.mark.parametrize(
    "value, expected",
    [
        (1757600000, 1757600000),
        (1757600000.0, 1757600000),
        ("1757600000", 1757600000),
        (True, None),
        (0, None),
        (-5, None),
        ("yesterday", None),
        (None, None),
        (1757600000.5, None),
    ],
)
def test_auth_time_is_read_as_epoch_seconds_or_not_at_all(value, expected):
    assert read_assurance({"auth_time": value}).auth_time == expected


@pytest.mark.parametrize("value", [123, ["phr"], "", "  ", "x" * 300])
def test_an_acr_that_is_not_one_string_is_dropped(value):
    assert read_assurance({"acr": value}).acr is None


def test_the_session_amr_names_the_provider_and_what_it_used():
    assurance = read_assurance({"amr": ["mfa", "pwd"]})
    assert session_amr("acme", assurance) == ["mfa", "oidc:acme", "pwd"]


def test_the_session_amr_names_the_provider_even_when_the_idp_is_silent():
    assert session_amr("acme", ProviderAssurance()) == ["oidc:acme"]


def test_a_provider_replaces_only_its_own_entry():
    prior = {
        "4": {"auth_time": 100, "amr": ["pwd"]},
        "9": {"auth_time": 200, "amr": ["mfa"]},
    }
    merged = record_for_provider(
        prior,
        provider_id=4,
        assurance=ProviderAssurance(auth_time=300, amr=("mfa", "hwk")),
    )
    assert merged == {
        "4": {"auth_time": 300, "amr": ["mfa", "hwk"]},
        "9": {"auth_time": 200, "amr": ["mfa"]},
    }


def test_a_first_provider_starts_the_record():
    assert record_for_provider(
        None, provider_id=7, assurance=ProviderAssurance(auth_time=1)
    ) == {"7": {"auth_time": 1}}


def test_an_entry_that_is_not_an_object_is_not_carried_forward():
    merged = record_for_provider(
        {"4": "pwd", "9": {"auth_time": 2}},
        provider_id=1,
        assurance=ProviderAssurance(auth_time=3),
    )
    assert merged == {"1": {"auth_time": 3}, "9": {"auth_time": 2}}


def test_a_provider_that_now_says_nothing_leaves_no_stale_account():
    merged = record_for_provider(
        {"4": {"auth_time": 100, "amr": ["mfa"]}, "9": {"auth_time": 2}},
        provider_id=4,
        assurance=ProviderAssurance(),
    )
    assert merged == {"9": {"auth_time": 2}}


def test_the_record_is_bounded_and_keeps_the_provider_just_used():
    prior = {
        str(pid): {"auth_time": pid} for pid in range(1, MAX_TRACKED_PROVIDERS + 5)
    }
    merged = record_for_provider(
        prior, provider_id=999, assurance=ProviderAssurance(auth_time=1)
    )
    assert len(merged) == MAX_TRACKED_PROVIDERS
    assert "999" in merged
    # The least recently authenticated fall off first.
    assert "1" not in merged
    assert str(MAX_TRACKED_PROVIDERS + 4) in merged
