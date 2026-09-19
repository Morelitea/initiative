"""What a guild holds, given what an operator ticked.

Two switches, neither nested under the other. The reading lives in one pure
function, so this is where it is pinned: every gate and the community's own
settings page read their answer from it.
"""

import pytest

from app.core.guild_auth_options import GuildAuthOption, effective_options

pytestmark = pytest.mark.unit


def test_a_guild_granted_nothing_holds_nothing():
    assert effective_options([]) == frozenset()
    assert effective_options(None) == frozenset()


def test_each_switch_stands_on_its_own():
    """Neither implies the other, and neither needs the other to count."""
    assert effective_options(["providers"]) == frozenset({GuildAuthOption.providers})
    assert effective_options(["restrictions"]) == frozenset(
        {GuildAuthOption.restrictions}
    )


def test_both_together_is_both():
    assert effective_options(["restrictions", "providers"]) == frozenset(
        {GuildAuthOption.restrictions, GuildAuthOption.providers}
    )


def test_a_label_this_build_does_not_know_is_dropped():
    """The column is an enum, so a value from a newer build reads as nothing —
    and the one a former build wrote is treated the same way."""
    assert effective_options(["providers", "saml"]) == frozenset(
        {GuildAuthOption.providers}
    )
    assert effective_options(["providers", "require_sign_in"]) == frozenset(
        {GuildAuthOption.providers}
    )


def test_every_option_counts_when_granted():
    """Drift guard: an option added to the enum counts by being in it, rather
    than by anybody remembering to list it here."""
    stored = [option.value for option in GuildAuthOption]
    assert effective_options(stored) == frozenset(GuildAuthOption)
