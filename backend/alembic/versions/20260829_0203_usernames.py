"""Give every account a handle, and every guild a say in which name it shows.

A handle is a name part plus a number — ``foobar#1234`` — unique as a pair, so
a requested name is essentially always available and nobody inherits a
``jordan-37``.

Existing rows are seeded from first initial + last name (``Lee Janzen`` ->
``ljanzen``). A row with no name, or whose name is an address (an SSO account
with no name claim stored its address there), gets a generated name instead: an
address never becomes a handle. ``username_chosen`` stays false for every
seeded row, which is what routes its owner to the pick screen on their next
sign-in.

Everything this revision writes is spelled out here rather than read from
``app.core.usernames``: a revision states what it does to the databases
upgrading through it, and a word list or a slug rule that changes later must
not reach back and change that.

Also adds ``guilds.show_member_names``: off means the guild renders handles,
and a community-listed guild can never turn it on, which is a CHECK rather
than an app rule.
"""

import random
import unicodedata

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260829_0203"
down_revision = "20260828_0202"
branch_labels = None
depends_on = None

_BATCH = 500

# Frozen at this revision — see the module docstring.
_MIN_LENGTH = 3
_MAX_LENGTH = 32
_DISCRIMINATOR_MIN = 0
_DISCRIMINATOR_MAX = 9999
_LOWER = frozenset("abcdefghijklmnopqrstuvwxyz")
_DIGITS = frozenset("0123456789")
_RESERVED = frozenset(
    {
        "admin",
        "administrator",
        "anonymous",
        "api",
        "deleted",
        "everyone",
        "guild",
        "here",
        "initiative",
        "me",
        "moderator",
        "operator",
        "owner",
        "root",
        "staff",
        "support",
        "system",
        "user",
    }
)
_ADJECTIVES = (
    "amber",
    "arctic",
    "bold",
    "brass",
    "brave",
    "bright",
    "calm",
    "clever",
    "copper",
    "coral",
    "crimson",
    "curious",
    "dawn",
    "eager",
    "early",
    "fair",
    "gentle",
    "glad",
    "golden",
    "hardy",
    "hazel",
    "indigo",
    "ivory",
    "jade",
    "keen",
    "lively",
    "lucky",
    "merry",
    "mellow",
    "noble",
    "olive",
    "opal",
    "patient",
    "quiet",
    "rapid",
    "royal",
    "sable",
    "sage",
    "scarlet",
    "silver",
    "smooth",
    "solar",
    "spry",
    "steady",
    "sunny",
    "swift",
    "teal",
    "tidy",
    "velvet",
    "vivid",
    "warm",
    "willow",
    "witty",
    "zesty",
)
_NOUNS = (
    "alder",
    "anchor",
    "arrow",
    "aspen",
    "badger",
    "beacon",
    "birch",
    "bison",
    "bramble",
    "cedar",
    "comet",
    "cove",
    "crane",
    "dahlia",
    "delta",
    "ember",
    "falcon",
    "fern",
    "finch",
    "harbor",
    "heron",
    "ibis",
    "juniper",
    "kestrel",
    "lantern",
    "lark",
    "lichen",
    "lotus",
    "lynx",
    "maple",
    "marten",
    "meadow",
    "otter",
    "pine",
    "quarry",
    "quill",
    "raven",
    "reef",
    "ridge",
    "sable",
    "sparrow",
    "spruce",
    "summit",
    "thistle",
    "thrush",
    "trellis",
    "vale",
    "walnut",
    "willow",
    "wren",
)


def _slugify(seed: str | None) -> str | None:
    """The name-part rules as they stand at this revision."""
    if not seed:
        return None
    text = seed.strip()
    if not text or "@" in text:
        return None

    decomposed = unicodedata.normalize("NFKD", text)
    folded = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()

    kept: list[str] = []
    for character in folded:
        if character in _LOWER or character in _DIGITS:
            kept.append(character)
        elif character in "-_" or character.isspace():
            if kept and kept[-1] != "-":
                kept.append("-")

    slug = "".join(kept).strip("-")[:_MAX_LENGTH].rstrip("-")
    while slug and slug[0] not in _LOWER:
        slug = slug[1:]
    if len(slug) < _MIN_LENGTH or slug in _RESERVED:
        return None
    return slug


def _from_full_name(full_name: str | None) -> str | None:
    """First initial + last name: ``Lee Janzen`` -> ``ljanzen``."""
    text = (full_name or "").strip()
    if not text:
        return None
    tokens = text.split()
    if len(tokens) == 1:
        return _slugify(tokens[0])
    return _slugify(f"{tokens[0][0]}{tokens[-1]}")


def _generated_name(rng: random.Random) -> str:
    return f"{rng.choice(_ADJECTIVES)}-{rng.choice(_NOUNS)}"


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

    rng = random.Random()
    assign = sa.text(
        "UPDATE public.users SET username = :name, discriminator = :discriminator "
        "WHERE id = :user_id"
    )

    # Every pair handed out in this run, keyed the way ``ix_users_handle``
    # compares them — on the lowercased name — so two spellings of one name
    # cannot both draw the same number and fail the index below.
    taken: dict[str, set[int]] = {}

    def _claim(name: str) -> int | None:
        used = taken.setdefault(name.lower(), set())
        if len(used) > _DISCRIMINATOR_MAX - _DISCRIMINATOR_MIN:
            return None
        while True:
            number = rng.randint(_DISCRIMINATOR_MIN, _DISCRIMINATOR_MAX)
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
            seed = None if status == "anonymized" else _from_full_name(full_name)
            name = seed or _generated_name(rng)
            number = _claim(name)
            while number is None:
                name = _generated_name(rng)
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
        f"discriminator BETWEEN {_DISCRIMINATOR_MIN} AND {_DISCRIMINATOR_MAX}",
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
