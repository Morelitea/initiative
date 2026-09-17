"""What a guild holds, given what an operator ticked.

The nesting lives in one pure function, so this is where it is pinned: every
gate and the community's own settings page read their answer from it.
"""

import pytest

from app.core.guild_auth_options import GuildAuthOption, effective_options

pytestmark = pytest.mark.unit


def test_a_guild_granted_nothing_holds_nothing():
    assert effective_options([]) == frozenset()
    assert effective_options(None) == frozenset()


def test_the_master_alone_is_the_surface_and_nothing_under_it():
    """The tab, and the two switches that have no option of their own."""
    assert effective_options(["restrictions"]) == frozenset(
        {GuildAuthOption.restrictions}
    )


def test_an_option_ticked_under_a_master_nobody_granted_counts_for_nothing():
    """Every one of them hangs off it, so without it there is nothing to hang."""
    assert effective_options(["providers", "require_sign_in"]) == frozenset()


def test_the_master_lets_the_ones_beneath_it_through():
    assert effective_options(["restrictions", "providers"]) == frozenset(
        {GuildAuthOption.restrictions, GuildAuthOption.providers}
    )


def test_a_label_this_build_does_not_know_is_dropped():
    """The column is an enum, so a value from a newer build reads as nothing."""
    assert effective_options(["restrictions", "saml"]) == frozenset(
        {GuildAuthOption.restrictions}
    )


def test_every_option_is_reachable_with_the_master():
    """Drift guard: an option added to the enum joins the nesting by being in
    it, rather than by anybody remembering to list it here."""
    stored = [option.value for option in GuildAuthOption]
    assert effective_options(stored) == frozenset(GuildAuthOption)
