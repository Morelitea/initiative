"""guild banner layout: where the copy sits, and how the banner ends

Two more identity columns on ``public.guilds``, beside the two colours the
guild-images revision added:

* ``banner_text_align`` — ``center`` or ``left``. Where the guild's name and
  description sit across the banner's width.
* ``banner_fade`` — ``none``, ``weak``, or ``strong``. Whether the banner stops
  at an edge or is extended past it and dissolved into the page, with the
  page's own content riding over the tail.

``banner_text_align`` defaults to what every existing banner already is, so no
guild's copy moves. ``banner_fade`` deliberately does not: it defaults to
``strong``, because a banner reads better as the top of a page than as a strip
laid on one, and a hard edge is the thing worth opting into rather than the
thing worth defaulting to. Every existing guild's banner therefore starts
dissolving into its page, and a guild that prefers the edge sets ``none``.

Both carry a CHECK for the reason the colour columns do: the values are read
straight into a stylesheet, so the database is where the vocabulary is settled
rather than only the schema that happens to be in front of it.

The enums are spelled out as literals here rather than read from
``BannerTextAlign``/``BannerFade``. A revision states what it writes: adding a
third alignment later is the next migration's business, not a change to what
this one did to databases upgrading through it.

They join the column-scoped UPDATE grant a guild's own admins hold on
``public.guilds`` — the grant is what makes "a guild admin may set this, and
may not set a cap" a database fact rather than an application one. A
column-scoped GRANT adds to nothing, so the grant is restated in full each time
it changes.

Restating it also picks up ``show_member_names``, which 0203 added to the table
without adding to this grant — so a guild admin's PATCH could set it in the
session and be refused by Postgres on flush. The downgrade puts the grant back
exactly as 0203 left it, that gap included: a downgrade restores the state it
is going back to, not an improved one.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260829_0206"
down_revision = "20260829_0205"
branch_labels = None
depends_on = None


_DEFAULT_TEXT_ALIGN = "center"
_TEXT_ALIGNS = "'center', 'left'"
_DEFAULT_FADE = "strong"
_FADES = "'none', 'weak', 'strong'"

_GUILD_ADMIN_COLUMNS = (
    "name, description, is_community, categories, "
    "has_adult_content, show_member_names, "
    "banner_color, banner_text_color, banner_text_align, banner_fade, "
    "updated_at"
)
#: The grant as 0203 left it — no ``show_member_names``; see the note above.
_PREVIOUS_GUILD_ADMIN_COLUMNS = (
    "name, description, is_community, categories, "
    "has_adult_content, banner_color, banner_text_color, updated_at"
)


def _grant(columns: str) -> None:
    """Replace the guild-admin UPDATE grant with exactly ``columns``."""
    op.execute("REVOKE UPDATE ON TABLE public.guilds FROM app_guild_base")
    op.execute(f"GRANT UPDATE ({columns}) ON TABLE public.guilds TO app_guild_base")


def upgrade() -> None:
    for column, default, check in (
        (
            "banner_text_align",
            _DEFAULT_TEXT_ALIGN,
            f"banner_text_align IN ({_TEXT_ALIGNS})",
        ),
        ("banner_fade", _DEFAULT_FADE, f"banner_fade IN ({_FADES})"),
    ):
        op.add_column(
            "guilds",
            sa.Column(
                column, sa.String(length=8), nullable=False, server_default=default
            ),
        )
        op.create_check_constraint(f"ck_guilds_{column}", "guilds", check)
    _grant(_GUILD_ADMIN_COLUMNS)


def downgrade() -> None:
    _grant(_PREVIOUS_GUILD_ADMIN_COLUMNS)
    # ``IF EXISTS`` on both, as the revision that added the colour columns does:
    # a downgrade brings the table back from whatever shape it is actually in,
    # not only from the one a complete upgrade leaves.
    for column in ("banner_text_align", "banner_fade"):
        op.execute(
            f"ALTER TABLE public.guilds DROP CONSTRAINT IF EXISTS ck_guilds_{column}"
        )
        op.execute(f"ALTER TABLE public.guilds DROP COLUMN IF EXISTS {column}")
