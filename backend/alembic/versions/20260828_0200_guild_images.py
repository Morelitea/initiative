"""guild images: icons and banners in one place

Everything a guild is *pictured* by now lives in one ``public`` table,
``guild_images``, one row per (guild, variant): its ``icon``, and the two
renditions of its banner (``full`` for the guild's own front page, ``card`` for
its community-directory card).

The icon moves here from ``guilds.icon_base64``, where it was a data URI
inlined into every payload that named a guild. Two reasons, and the second is
why it happens now rather than later:

* it has the banner's audience problem exactly — a listed guild's icon is shown
  to people who are not in the guild — and the same answer, so it may as well
  be the same mechanism;
* a directory card that fetched its banner as a cached immutable URL while
  carrying its icon inline in the same JSON would be two mechanisms for two
  pictures on one card.

The bytes are in ``public`` rather than in a guild schema because of who reads
them: a stranger browsing the directory holds no role that could reach
``guild_<id>``. That makes these guild *identity*, like the name and
description they sit beside on ``public.guilds``, rather than guild content —
so they are also outside the guild's storage quota.

Every guild has a banner from the moment it exists: the artwork it uploaded, or
a flat colour. Two more identity columns on ``public.guilds`` carry it —
``banner_color`` fills the banner where there is no artwork, and
``banner_text_color`` is what the guild's name and description are written in,
over either. Both are NOT NULL with defaults, so no path downstream has a
"guild with no banner" case to render, and both cost no request and no storage.

The defaults are literals here, as every value a revision writes must be: a
migration cannot ask the running app what its accent is, and a value that
changed later would reach back and change what this one did.

Whether a given guild may upload banner artwork is an operator entitlement on
``guild_administration`` — ``banner_image_enabled``, defaulted ON so nothing
changes for an existing guild or a self-hosted install. Like the caps beside
it, it is a stored flag the app reads; it is never derived from ``tier_name``,
which stays display-only. It gates uploading, never serving: a banner a guild
already has keeps being shown.

Access shape, split by what each half needs to know:

* **The bytes are the system engine's alone.** Whether a stranger may see a
  guild's icon or card rendition depends on a listing that stranger holds no
  role to read, so that decision is made in one place — the serving endpoint,
  via ``app.services.platform.guild_images.may_read_image`` — and no
  request-path role holds a table grant here.
* **A member may learn that their own guild has an image, and its digest**, so
  their guild list can name the URL without a second engine. That much is a
  membership fact and is expressed as one: a column-scoped ``SELECT`` on
  ``(guild_id, variant, sha256)`` under a policy that admits the guild the
  session is routed into or one the caller belongs to. ``data`` is not in that
  grant, so the request path can never select an image's bytes.

The schema's default grants make every new ``public`` table writable by the
routed base roles, so they are wound back explicitly before anything else.

The carry-over holds legacy icons to the standard a new one is held to, rather
than grandfathering whatever ``icon_base64`` happened to contain: raster
(PNG/JPEG/WebP/GIF), square, no larger than the icon rendition, and inside its
weight limit. Everything else is left behind — an SVG especially, since an icon
used to be a data URI in an ``<img>`` and is now a URL this deployment serves,
which is not a form SVG is safe in. A guild whose icon does not qualify falls
back to its lettered avatar and can upload one that does. What was carried and
what was dropped is logged.
"""

import base64
import hashlib
import logging
import struct

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from app.core.config import settings

logger = logging.getLogger("alembic.runtime.migration")

revision = "20260828_0200"
down_revision = "20260828_0199"
branch_labels = None
depends_on = None


# NULLIF-guarded: an unset context leaves the setting empty, and a bare
# ''::int would raise and fault the whole query rather than fail the policy.
_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"
_GUILD_ID = "NULLIF(current_setting('app.current_guild_id', true), '')::int"

# The caller belongs to the guild whose image this row is. Evaluated with the
# querying role's own privileges, which is why it reads a table every request
# role can already see its own rows in.
_IMAGE_MEMBER = (
    "EXISTS (SELECT 1 FROM public.guild_memberships "
    "WHERE guild_memberships.guild_id = guild_images.guild_id "
    f"AND guild_memberships.user_id = {_USER_ID})"
)

# Spelled out rather than read from ``GuildImageVariant``: a revision states
# what it writes, so adding a variant later changes the next migration rather
# than reaching back and changing what this one did.
_VARIANT_LITERALS = "'icon', 'card', 'full'"

# What a guild's banner is before anyone touches it. Literals, because a
# revision states the values it writes: it cannot ask the running app what its
# accent is, and a value that changed later would reach back and change what
# this revision did to databases upgrading through it.
_DEFAULT_BANNER_COLOR = "#2563eb"
_DEFAULT_BANNER_TEXT_COLOR = "#ffffff"
# Banner text is one of exactly two colours: a fill is the guild's to pick and
# artwork can be anything, so the words on it stay readable only by sitting at
# one end of the scale or the other.
_BANNER_TEXT_COLORS = "'#ffffff', '#000000'"

# What a legacy icon must be to come across, spelled out here rather than read
# from ``IMAGE_SPECS`` — a revision states what it accepted, so tightening the
# rule later changes the next migration rather than what this one did.
_ICON_MIMES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
_ICON_MAX_EDGE = 256
_ICON_MAX_BYTES = 64 * 1024
_ICON_RATIO_TOLERANCE = 0.02

# ``icon_base64`` leaves the guild-admin column grant; the two banner colours
# join it. The images themselves are written by the system engine, not through
# this grant.
_GUILD_ADMIN_COLUMNS = (
    "name, description, is_community, categories, "
    "has_adult_content, banner_color, banner_text_color, updated_at"
)


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def _decode_data_uri(uri: str) -> tuple[str, bytes] | None:
    """``(mime, bytes)`` from a ``data:image/…;base64,…`` URI, or None."""
    head, separator, payload = uri.partition(",")
    if not separator or not head.startswith("data:") or ";base64" not in head:
        return None
    mime = head[len("data:") :].split(";", 1)[0].strip().lower()
    try:
        return mime, base64.b64decode(payload, validate=True)
    except (ValueError, base64.binascii.Error):
        return None


#: JPEG frame markers that carry the image dimensions.
_JPEG_SOF = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


def _dimensions(data: bytes) -> tuple[int, int] | None:
    """``(width, height)`` read from an image header, or None if it is not one.

    Spelled out here rather than imported: this revision decides which legacy
    icons it carried, and a probe that changes later must not reach back and
    change that. It parses headers rather than decoding, so nothing hands these
    bytes to an image library.
    """
    # Each branch checks it has the bytes it is about to read: a stored icon
    # can carry a format's opening marks and stop before its dimensions, and a
    # short read here would fault the upgrade rather than skip one icon.
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR" and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return int(width), int(height)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            return (
                int.from_bytes(data[24:27], "little") + 1,
                int.from_bytes(data[27:30], "little") + 1,
            )
        if chunk == b"VP8 " and len(data) >= 30:
            return (
                struct.unpack("<H", data[26:28])[0] & 0x3FFF,
                struct.unpack("<H", data[28:30])[0] & 0x3FFF,
            )
        if chunk == b"VP8L" and len(data) >= 25:
            bits = int.from_bytes(data[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        return None
    if data[:2] == b"\xff\xd8":
        index, length = 2, len(data)
        while index + 3 < length:
            if data[index] != 0xFF:
                return None
            marker = data[index + 1]
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                index += 2
                continue
            if marker in _JPEG_SOF:
                if index + 9 > length:
                    return None
                height, width = struct.unpack(">HH", data[index + 5 : index + 9])
                return int(width), int(height)
            index += 2 + struct.unpack(">H", data[index + 2 : index + 4])[0]
    return None


def _qualifies(mime: str, data: bytes) -> bool:
    """Whether this legacy icon meets the standard a new upload is held to."""
    if mime not in _ICON_MIMES or not data or len(data) > _ICON_MAX_BYTES:
        return False
    probed = _dimensions(data)
    if probed is None:
        return False
    width, height = probed
    if height <= 0 or width > _ICON_MAX_EDGE or height > _ICON_MAX_EDGE:
        return False
    return abs(width / height - 1.0) <= _ICON_RATIO_TOLERANCE


def _carry_over_icons() -> None:
    """Move every qualifying ``guilds.icon_base64`` into ``guild_images``.

    ``public.guilds`` is FORCE RLS and the migration runs as the table's owner,
    so a plain SELECT here returns **zero** rows and the copy would succeed
    having moved nothing. Lift FORCE for the length of the read, restore it in
    the same transaction, and check that everything decided-to-carry landed
    before going on to drop the column it came from (migration 0179 does the
    same, for the same reason).

    The reading and the deciding happen in Python rather than in SQL because
    what qualifies depends on an image header, which SQL has no business
    parsing.
    """
    conn = op.get_bind()
    op.execute("ALTER TABLE public.guilds NO FORCE ROW LEVEL SECURITY")
    try:
        legacy = conn.execute(
            text(
                "SELECT id, created_by, icon_base64 FROM public.guilds "
                "WHERE icon_base64 IS NOT NULL"
            )
        ).all()
    finally:
        op.execute("ALTER TABLE public.guilds FORCE ROW LEVEL SECURITY")

    carried: list[dict] = []
    dropped = 0
    for guild_id, created_by, uri in legacy:
        decoded = _decode_data_uri(uri)
        if decoded is None or not _qualifies(*decoded):
            dropped += 1
            continue
        mime, data = decoded
        carried.append(
            {
                "guild_id": guild_id,
                "variant": "icon",
                "sha256": hashlib.sha256(data).hexdigest(),
                "content_type": mime,
                "byte_size": len(data),
                "data": data,
                "created_by": created_by,
            }
        )

    if carried:
        conn.execute(
            text(
                "INSERT INTO public.guild_images "
                "(guild_id, variant, sha256, content_type, byte_size, data, "
                "created_by, created_at) VALUES "
                "(:guild_id, :variant, :sha256, :content_type, :byte_size, "
                ":data, :created_by, now())"
            ),
            carried,
        )
    landed = conn.execute(
        text("SELECT count(*) FROM public.guild_images WHERE variant = 'icon'")
    ).scalar_one()
    if landed != len(carried):
        raise RuntimeError(
            f"guild icon carry-over stored {landed} of {len(carried)} icons; "
            "aborting rather than dropping the column they came from"
        )
    logger.info(
        "guild icon carry-over: %d carried, %d left behind "
        "(not raster, not square, or too large for the icon rendition)",
        len(carried),
        dropped,
    )


def upgrade() -> None:
    # A CHECK on each rather than only a schema validator: these values are
    # interpolated into a style attribute, and one of them is an accessibility
    # floor — so the database is where both are settled, for every path that
    # can write them.
    for column, default, check in (
        (
            "banner_color",
            _DEFAULT_BANNER_COLOR,
            "banner_color ~ '^#[0-9a-f]{6}$'",
        ),
        (
            "banner_text_color",
            _DEFAULT_BANNER_TEXT_COLOR,
            f"banner_text_color IN ({_BANNER_TEXT_COLORS})",
        ),
    ):
        op.add_column(
            "guilds",
            sa.Column(
                column, sa.String(length=7), nullable=False, server_default=default
            ),
        )
        op.create_check_constraint(f"ck_guilds_{column}", "guilds", check)
    # Operator entitlement, beside the caps and the sign-in one. Defaulted ON so
    # every existing guild — and every self-hosted install — keeps the whole
    # feature. Read-only to every request-path role, like the rest of this
    # table: no login role writes a guild's entitlements.
    op.add_column(
        "guild_administration",
        sa.Column(
            "banner_image_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    op.create_table(
        "guild_images",
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("variant", sa.String(length=8), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("guild_id", "variant"),
        sa.CheckConstraint(
            f"variant IN ({_VARIANT_LITERALS})", name="ck_guild_images_variant"
        ),
    )

    base = _platform("base")
    request_roles = f'app_guild_base, "{base}", app_user'
    _run(
        [
            "ALTER TABLE public.guild_images ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE public.guild_images FORCE ROW LEVEL SECURITY",
            f"REVOKE ALL ON TABLE public.guild_images FROM {request_roles}",
            "GRANT SELECT, INSERT, DELETE ON TABLE public.guild_images TO app_admin",
            # Column-scoped, so a request-path role can name an image but never
            # read one. Table-level grants stay revoked above, which is what the
            # system_grants registry records.
            "GRANT SELECT (guild_id, variant, sha256) ON public.guild_images "
            f"TO {request_roles}",
            "DROP POLICY IF EXISTS guild_image_member_read ON public.guild_images",
            "CREATE POLICY guild_image_member_read ON public.guild_images "
            f"AS PERMISSIVE FOR SELECT TO {request_roles} USING ("
            f"guild_id = {_GUILD_ID} OR {_IMAGE_MEMBER})",
        ]
    )

    _carry_over_icons()

    op.execute("REVOKE UPDATE ON TABLE public.guilds FROM app_guild_base")
    op.execute(
        f"GRANT UPDATE ({_GUILD_ADMIN_COLUMNS}) ON TABLE public.guilds "
        "TO app_guild_base"
    )
    op.drop_column("guilds", "icon_base64")


def downgrade() -> None:
    op.execute("ALTER TABLE public.guilds ADD COLUMN IF NOT EXISTS icon_base64 text")
    conn = op.get_bind()
    op.execute("ALTER TABLE public.guilds NO FORCE ROW LEVEL SECURITY")
    try:
        conn.execute(
            text(
                "UPDATE public.guilds g SET icon_base64 = "
                "'data:' || i.content_type || ';base64,' || "
                "encode(i.data, 'base64') "
                "FROM public.guild_images i "
                "WHERE i.guild_id = g.id AND i.variant = 'icon'"
            )
        )
    finally:
        op.execute("ALTER TABLE public.guilds FORCE ROW LEVEL SECURITY")

    op.execute("REVOKE UPDATE ON TABLE public.guilds FROM app_guild_base")
    op.execute(
        "GRANT UPDATE (name, description, icon_base64, is_community, categories, "
        "has_adult_content, updated_at) ON TABLE public.guilds TO app_guild_base"
    )
    _run(
        [
            "DROP POLICY IF EXISTS guild_image_member_read ON public.guild_images",
            "ALTER TABLE public.guild_images DISABLE ROW LEVEL SECURITY",
        ]
    )
    op.drop_table("guild_images")
    op.drop_column("guild_administration", "banner_image_enabled")
    # ``IF EXISTS`` on both: a downgrade has to bring the table back from
    # whatever shape it is actually in, not only from the one the upgrade above
    # leaves. (It also lets this revision be re-applied over a database that
    # stopped part-way through it.)
    for column in ("banner_color", "banner_text_color"):
        op.execute(
            f"ALTER TABLE public.guilds DROP CONSTRAINT IF EXISTS ck_guilds_{column}"
        )
        op.execute(f"ALTER TABLE public.guilds DROP COLUMN IF EXISTS {column}")
