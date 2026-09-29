"""What a routing shape refuses to be built as.

The combinations the keyword form had to refuse at the call — a grant carrying
a membership's community, a narrowing with nothing to narrow — cannot be
written with the shapes. What is left is checked when a shape is built.
"""

import pytest

from app.db.guild_standing import GuildContext
from app.db.request_context import (
    ContentGrantee,
    ContextShapeError,
    Member,
    SettingsGrantee,
)


def test_a_person_in_a_community_takes_the_standing_the_seam_computes():
    for shape in (Member, SettingsGrantee):
        with pytest.raises(ContextShapeError):
            shape(guild_id=3, user_id=7, standing=None)
    # The grant lookup routes before any standing exists.
    assert ContentGrantee(guild_id=3, user_id=7).standing is None
    standing = GuildContext(guild=None, user_id=7, guild_id=3)
    assert Member(guild_id=3, user_id=7, standing=standing).guild_id == 3
