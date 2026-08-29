"""Give every account a handle, and every guild a say in which name it shows.

A handle is a name part plus a number — ``foobar#1234`` — unique as a pair, so
a requested name is essentially always available and nobody inherits a
``jordan-37``.

Existing rows are seeded from the first token of ``full_name``. A row with no
name, or whose name is an address (an SSO account with no name claim stored
its address there), gets a generated name instead: an address never becomes a
handle. ``username_chosen`` stays false for every seeded row, which is what
routes its owner to the pick screen on their next sign-in.

Also adds ``guilds.show_member_names``: off means the guild renders handles,
and a community-listed guild can never turn it on, which is a CHECK rather
than an app rule.
"""

import sqlalchemy as sa
from alembic import op

from app.core import usernames
from app.core.config import settings

revision = "20260829_0203"
down_revision = "20260828_0202"
branch_labels = None
depends_on = None

_BATCH = 500


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def _seed_handles(conn) -> None:
    """Give every existing row a handle, and prove that every row got one.

    ``public.users`` is FORCE ROW LEVEL SECURITY — policy-bound even for the
    owner this migration runs as — so a naive read would match zero rows and
    the NOT NULL below would then fail on data it never saw. The flag is
    lifted and restored around the seeding, inside the same transaction, and
    the result is asserted against a count taken the same way.
    """
    op.execute("ALTER TABLE public.users NO FORCE ROW LEVEL SECURITY")
    try:
        _write_handles(conn)
    finally:
        op.execute("ALTER TABLE public.users FORCE ROW LEVEL SECURITY")


def _write_handles(conn) -> None:
    expected = conn.execute(sa.text("SELECT count(*) FROM public.users")).scalar_one()
    if not expected:
        return

    assign = sa.text(
        "UPDATE public.users SET username = :name, discriminator = :discriminator "
        "WHERE id = :user_id"
    )
    # Every pair handed out in this run, so the seeding does not have to read
    # its own writes back one row at a time.
    taken: dict[str, set[int]] = {}

    def _claim(name: str) -> int | None:
        used = taken.setdefault(name, set())
        if len(used) > usernames.DISCRIMINATOR_MAX:
            return None
        while True:
            number = usernames.random_discriminator()
            if number not in used:
                used.add(number)
                return number

    written = 0
    last_id = 0
    while True:
        rows = conn.execute(
            sa.text(
                "SELECT id, full_name, status FROM public.users "
                "WHERE id > :last ORDER BY id LIMIT :limit"
            ),
            {"last": last_id, "limit": _BATCH},
        ).all()
        if not rows:
            break
        for user_id, full_name, status in rows:
            last_id = user_id
            # An anonymized row holds no personal data to carry over.
            seed = (
                None if status == "anonymized" else usernames.first_name_of(full_name)
            )
            name = seed or usernames.random_name()
            number = _claim(name)
            while number is None:
                name = usernames.random_name()
                number = _claim(name)
            conn.execute(
                assign, {"name": name, "discriminator": number, "user_id": user_id}
            )
            written += 1

    if written != expected:  # pragma: no cover - the assertion is the point
        raise RuntimeError(
            f"username backfill wrote {written} of {expected} rows; "
            "refusing to make the column NOT NULL"
        )


def upgrade() -> None:
    conn = op.get_bind()

    op.add_column("users", sa.Column("username", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("discriminator", sa.SmallInteger(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "username_chosen",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    _seed_handles(conn)

    op.alter_column("users", "username", nullable=False)
    op.alter_column("users", "discriminator", nullable=False)
    op.create_check_constraint(
        "ck_users_discriminator_range",
        "users",
        f"discriminator BETWEEN {usernames.DISCRIMINATOR_MIN} "
        f"AND {usernames.DISCRIMINATOR_MAX}",
    )
    # Unique on the pair, case-insensitively on the name part: a handle never
    # differs from another by case alone.
    op.execute(
        "CREATE UNIQUE INDEX ix_users_handle "
        "ON public.users (lower(username), discriminator)"
    )

    # 0144 replaced the request path's table-wide UPDATE on ``public.users``
    # with a column list computed from the catalog at that revision, so a column
    # added later is not in it. Name the new ones explicitly — the own-row
    # policies from 0202 still decide *whose* row they reach.
    for role in ("app_user", "app_guild_base", _platform_base()):
        op.execute(
            "GRANT UPDATE (username, discriminator, username_chosen) "
            f'ON TABLE public.users TO "{role}"'
        )

    op.add_column(
        "guilds",
        sa.Column(
            "show_member_names",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_check_constraint(
        "ck_guilds_community_member_names",
        "guilds",
        "NOT (is_community AND show_member_names)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_guilds_community_member_names", "guilds", type_="check")
    op.drop_column("guilds", "show_member_names")
    op.execute("DROP INDEX IF EXISTS public.ix_users_handle")
    op.drop_constraint("ck_users_discriminator_range", "users", type_="check")
    op.drop_column("users", "username_chosen")
    op.drop_column("users", "discriminator")
    op.drop_column("users", "username")
