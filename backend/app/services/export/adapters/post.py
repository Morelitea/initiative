"""Post source adapter: the importable backup envelope (json).

A post's body is a Lexical editor state, so the envelope carries it whole and
an import rebuilds the notice exactly — the same thing the document envelope
does with ``content``. Rendered formats (md/pdf/docx) go through the Lexical
converter and are not offered yet; a notice exports as the thing it is.

What the envelope deliberately drops is the pin. A pin is a fact about the
board — "this is what matters here right now" — not about the notice, so
carrying it across would put an imported post above the posts already on
somebody else's board.

A notice that has not gone up is not exported at all — see
``posts.list_post_ids_for_export``. An export is a record of what a board has
said, and a scheduled draft has said nothing yet.

Access rule: READ on the post (exporting is a formatted read), enforced by the
``get_post_for_export`` seam at both count and build time, under the caller's
RLS session.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User
from app.models.tenant.post import Post
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.i18n import localize_now
from app.services.platform.csv_export import safe_filename_component


class PostAdapter:
    source = "post"
    template_id = "data-table"  # protocol requirement; json never renders one
    formats = frozenset({"json"})

    async def count(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> int:
        return len(await self._posts(session, user, guild_id, params))

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest:
        posts = await self._posts(session, user, guild_id, params)
        now = localize_now(datetime.now(timezone.utc), params.get("tz"))
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=tuple(build_post_item(post, format, now) for post in posts),
        )

    async def _posts(
        self, session: AsyncSession, user: User, guild_id: int, params: dict
    ) -> list[Post]:
        from app.services.export.adapters._common import selection_ids
        from app.services.tenant.posts import get_post_for_export

        return [
            await get_post_for_export(session, user, guild_id, post_id=pid)
            for pid in selection_ids(params, single_key="post_id", multi_key="post_ids")
        ]


def build_post_item(post: Post, format: str, now: datetime) -> RenderItem:
    date = now.strftime("%Y-%m-%d")
    stem = safe_filename_component(post.name).lower()
    # The envelope is importable machine data — stays canonical, never
    # localized (translating field keys breaks import).
    return RenderItem(
        key=f"{stem}-{date}.initiative-post",
        data=_envelope(post),
    )


def _envelope(post: Post) -> dict[str, Any]:
    return {
        "type": "initiative-post",
        "schema_version": 1,
        "name": post.name,
        "body": post.body or {},
        "tags": sorted(
            link.tag.name for link in post.tag_links or [] if link.tag is not None
        ),
    }
