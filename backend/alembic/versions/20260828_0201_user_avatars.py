"""user avatars

Move the picture on a user's profile out of ``users.avatar_base64`` — a text
column holding a base64 data URI, inlined into every payload that names a
person — and into ``public.user_avatars``, addressed by the digest of its
bytes so payloads carry a URL instead.

It is a table of its own rather than a ``bytea`` column on ``users`` because
the ORM names every mapped column in ``select(User)``, and naming a ``bytea``
is what makes Postgres reassemble it out of TOAST: a column here would put the
whole image on every user load in the app.

Access shape:

* **Anyone may read any avatar.** A name and a face are public information in
  this product, so the SELECT policy is unconditional and the serving endpoint
  answers before a session is routed.
* **Only you may write yours.** INSERT/UPDATE/DELETE are scoped to the calling
  user's own row by policy, so the request path cannot touch anyone else's
  picture even if a handler forgets to check.
* Removing *someone else's* — the moderation path, and anonymization — runs on
  the system engine, which is why no request-path policy mentions it.

The schema's default grants make every new ``public`` table writable by the
routed base roles, so they are wound back explicitly before anything else.
"""

import base64
import hashlib
import re

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260828_0201"
down_revision = "20260828_0200"
branch_labels = None
depends_on = None


# NULLIF-guarded: an unset context leaves the setting empty, and a bare
# ''::int would raise and fault the whole query rather than fail the policy.
_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"

_DATA_URI_RE = re.compile(
    r"^data:(?P<mime>image/[a-zA-Z0-9.+-]+);base64,(?P<payload>[A-Za-z0-9+/=\s]+)$"
)

#: Formats an avatar may be stored as. A legacy row in anything else (or in no
#: recognizable format at all) is reported and left behind rather than written
#: as something it is not.
_ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}

#: Rows per backfill batch. Each carries up to ~700 KB, so the whole set must
#: not be materialized at once.
_BATCH = 200


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def _decode(value: str) -> tuple[str, bytes] | None:
    """``data:image/…;base64,…`` -> ``(mime, bytes)``, or None if unusable."""
    match = _DATA_URI_RE.match(value.strip())
    if match is None:
        return None
    mime = match.group("mime").lower()
    if mime not in _ALLOWED_MIME:
        return None
    try:
        return mime, base64.b64decode(match.group("payload"), validate=False)
    except (ValueError, TypeError):
        return None


def _backfill(conn) -> None:
    """Copy every existing avatar across, and prove that it happened.

    ``public.users`` is FORCE ROW LEVEL SECURITY — policy-bound even for the
    owner this migration runs as — so a naive read would match zero rows and
    the column would then be dropped with the data still in it. The flag is
    lifted and restored around the copy, inside the same transaction, and the
    result is asserted against a count taken the same way.
    """
    op.execute("ALTER TABLE public.users NO FORCE ROW LEVEL SECURITY")
    try:
        _copy_avatars(conn)
    finally:
        op.execute("ALTER TABLE public.users FORCE ROW LEVEL SECURITY")


def _copy_avatars(conn) -> None:
    expected = conn.execute(
        sa.text("SELECT count(*) FROM public.users WHERE avatar_base64 IS NOT NULL")
    ).scalar_one()
    if not expected:
        return

    insert = sa.text(
        "INSERT INTO public.user_avatars "
        "(user_id, sha256, content_type, byte_size, width, height, data, created_at) "
        "VALUES (:user_id, :sha256, :content_type, :byte_size, NULL, NULL, "
        ":data, now()) "
        "ON CONFLICT (user_id) DO NOTHING"
    )

    written = 0
    skipped: list[int] = []
    last_id = 0
    while True:
        rows = conn.execute(
            sa.text(
                "SELECT id, avatar_base64 FROM public.users "
                "WHERE avatar_base64 IS NOT NULL AND id > :last "
                "ORDER BY id LIMIT :limit"
            ),
            {"last": last_id, "limit": _BATCH},
        ).all()
        if not rows:
            break
        for user_id, encoded in rows:
            last_id = user_id
            decoded = _decode(encoded)
            if decoded is None or not decoded[1]:
                skipped.append(user_id)
                continue
            mime, data = decoded
            conn.execute(
                insert,
                {
                    "user_id": user_id,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "content_type": mime,
                    "byte_size": len(data),
                    "data": data,
                },
            )
            written += 1

    if skipped:
        print(
            f"user_avatars backfill: {len(skipped)} row(s) held an unusable "
            f"avatar and were left behind (user ids: {sorted(skipped)[:20]})"
        )
    if written + len(skipped) != expected:
        raise RuntimeError(
            f"user_avatars backfill accounted for {written} written + "
            f"{len(skipped)} skipped of {expected} rows — refusing to drop "
            "users.avatar_base64 with data unaccounted for"
        )


def upgrade() -> None:
    op.create_table(
        "user_avatars",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        # Nullable because a row carried over from the old column has no
        # recorded size: reading one would mean parsing the image here, and a
        # revision must state what it writes rather than call into app code
        # that can change afterwards. Every row written since has both.
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    # The bytes are already compressed (PNG/JPEG/WebP), so the compression pass
    # EXTENDED would attempt before going out of line costs CPU on every write
    # and read for nothing.
    op.execute("ALTER TABLE public.user_avatars ALTER COLUMN data SET STORAGE EXTERNAL")

    base = _platform("base")
    request_roles = f'app_guild_base, "{base}", app_user'
    _run(
        [
            "ALTER TABLE public.user_avatars ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE public.user_avatars FORCE ROW LEVEL SECURITY",
            f"REVOKE ALL ON TABLE public.user_avatars FROM {request_roles}",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.user_avatars "
            "TO app_admin",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.user_avatars "
            f"TO {request_roles}",
            # Read: unconditional. A name and a face are public information
            # here, and the serving endpoint answers before a session exists.
            "DROP POLICY IF EXISTS user_avatar_public_read ON public.user_avatars",
            "CREATE POLICY user_avatar_public_read ON public.user_avatars "
            f"AS PERMISSIVE FOR SELECT TO {request_roles} USING (true)",
            # Write: your own row and no other. An unset context yields NULL,
            # which matches nothing, so these fail closed.
            "DROP POLICY IF EXISTS user_avatar_self_insert ON public.user_avatars",
            "CREATE POLICY user_avatar_self_insert ON public.user_avatars "
            f"AS PERMISSIVE FOR INSERT TO {request_roles} "
            f"WITH CHECK (user_id = {_USER_ID})",
            "DROP POLICY IF EXISTS user_avatar_self_update ON public.user_avatars",
            "CREATE POLICY user_avatar_self_update ON public.user_avatars "
            f"AS PERMISSIVE FOR UPDATE TO {request_roles} "
            f"USING (user_id = {_USER_ID}) WITH CHECK (user_id = {_USER_ID})",
            "DROP POLICY IF EXISTS user_avatar_self_delete ON public.user_avatars",
            "CREATE POLICY user_avatar_self_delete ON public.user_avatars "
            f"AS PERMISSIVE FOR DELETE TO {request_roles} "
            f"USING (user_id = {_USER_ID})",
        ]
    )

    _backfill(op.get_bind())
    op.drop_column("users", "avatar_base64")


def downgrade() -> None:
    op.add_column("users", sa.Column("avatar_base64", sa.Text(), nullable=True))
    conn = op.get_bind()
    # Same reason as the upgrade: users is FORCE RLS, so the restore would
    # silently match nothing.
    op.execute("ALTER TABLE public.users NO FORCE ROW LEVEL SECURITY")
    conn.execute(
        sa.text(
            "UPDATE public.users u SET avatar_base64 = "
            "'data:' || a.content_type || ';base64,' || encode(a.data, 'base64') "
            "FROM public.user_avatars a WHERE a.user_id = u.id"
        )
    )
    op.execute("ALTER TABLE public.users FORCE ROW LEVEL SECURITY")
    _run(
        [
            "DROP POLICY IF EXISTS user_avatar_self_delete ON public.user_avatars",
            "DROP POLICY IF EXISTS user_avatar_self_update ON public.user_avatars",
            "DROP POLICY IF EXISTS user_avatar_self_insert ON public.user_avatars",
            "DROP POLICY IF EXISTS user_avatar_public_read ON public.user_avatars",
            "ALTER TABLE public.user_avatars DISABLE ROW LEVEL SECURITY",
        ]
    )
    op.drop_table("user_avatars")
