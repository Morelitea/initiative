"""The member dataset — the people of the guild being read.

Grouping work by the person doing it was the one thing the old task sources
could do that a statement could not, because naming a person needs the account
projection and the query surface had no way to reach one.

What it reaches is not that projection but the guild's own view of it
(migration 0244): its members, decided by the guild the request is routed into
rather than by anything a statement says. So a query about people is a query
about *these* people, the ones a roster or a member picker would already show
the same reader.

``full_name`` is the guild's decision too, taken one layer further down — the
projection answers with a name only where the guild renders real names, so a
guild that does not has nothing here to select. ``display_name`` is the column
to group by either way: the real name where there is one, the handle where
there is not.
"""

from __future__ import annotations

from app.models.platform.user_profile_view import GuildMember
from app.services.fields.derive import derive_fields
from app.services.fields.spec import Dataset


def build() -> Dataset:
    return Dataset(
        model=GuildMember,
        # No tool: sharing governs things, and a person is not one. Who may
        # read this is settled by the routing, above the field registry.
        name_override="members",
        # The status line and the profile decorations are structured blobs, so
        # the derivation drops them: there is nothing a comparison would mean
        # against either.
        fields=derive_fields(
            GuildMember,
            # A view records no foreign keys, and this one *is* the account
            # table's own rows: its ``id`` is a person, however integer it
            # looks. Saying so is what gets it a member picker rather than a
            # number box — and what lets a reader pick themselves.
            references={"id": "users"},
        ),
    )
