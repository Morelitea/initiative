"""``initiative-wiki`` importer: the wiki row, its pages, the shape they sit
in, and the tags on both.

The tree arrives as slugs. Pages are written into the envelope in the order
the navigation draws them — siblings by position, not a walk down each branch
— so a child can appear before its parent. Every page is therefore created
first and filed second, once the whole slug map exists.

Sharing does not cross, here or in any other envelope: who may read a wiki is
a fact about the community it was written in. The importer owns what it
creates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.routed_guild import routed_guild_id
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.wiki import Wiki, WikiPage
from app.schemas.tenant.import_envelopes import WikiEnvelope, WikiPageEnvelope
from app.services.import_engine.common import ensure_tag, parse_datetime, unique_name
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.context import ImportContext
from app.services.import_engine.importers._base import (
    QuotesNobody,
    grant_ownership,
    parse_envelope,
)
from app.services.tenant import tags as tags_service
from app.services.tenant.wikis import slugify_page_title


class WikiImporter(QuotesNobody):
    envelope_type = "initiative-wiki"
    permission = PermissionKey.create_wikis

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(WikiEnvelope, envelope)

    def count(self, validated: BaseModel) -> int:
        envelope: WikiEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        # A wiki's size is what is written in it, plus the row naming it.
        return len(envelope.pages) + 1

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
        context: ImportContext | None = None,
    ) -> EnvelopeImportResult:
        env: WikiEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model
        guild_id = routed_guild_id()
        warnings: list[str] = []

        existing_names = {
            row
            for row in (
                await session.exec(
                    select(Wiki.name).where(Wiki.initiative_id == target_initiative.id)
                )
            ).all()
        }
        wiki = Wiki(
            name=unique_name(existing_names, env.name),
            description=env.description,
            initiative_id=target_initiative.id,
            created_by=importer.id,
        )
        session.add(wiki)
        await session.flush()

        await grant_ownership(
            session,
            tool=Tool.wiki,
            entity_id=wiki.id,
            target_initiative=target_initiative,
            importer=importer,
        )

        tags_created = 0
        tags_matched = 0

        async def attach_tags(surface: str, entity_id: int, names: list[str]) -> None:
            nonlocal tags_created, tags_matched
            for tag_name in names:
                resolved = await ensure_tag(
                    session, guild_id=guild_id, name=tag_name, color="#6b7280"
                )
                if resolved.created:
                    tags_created += 1
                else:
                    tags_matched += 1
                session.add(
                    tags_service.tag_edge(
                        tags_service.TAG_LINKS[surface], entity_id, resolved.id
                    )
                )

        await attach_tags("wiki", wiki.id, env.tags)

        # Pass one: every page exists before any page is filed.
        slugs = _assign_slugs(env.pages)
        page_ids: dict[str, int] = {}
        for page_env, slug in zip(env.pages, slugs):
            row = WikiPage(
                wiki_id=wiki.id,
                title=page_env.title,
                slug=slug,
                position=page_env.position,
                is_draft=page_env.is_draft,
                content=page_env.content or {},
                created_by=importer.id,
                # When it was written, where the envelope says so. Absent
                # leaves the model's own default — the moment of the import,
                # which is the only time this row can honestly claim.
                **_page_timestamps(page_env),
            )
            session.add(row)
            await session.flush()
            page_ids[slug] = row.id  # ty: ignore[invalid-assignment] — persisted row, id is set
            await attach_tags("wiki_page", row.id, page_env.tags)

        # Pass two: file each page under its parent, by slug.
        parents, cut_loops, unknown = _parent_slugs(env.pages, slugs)
        for slug, parent_slug in parents.items():
            parent_id = page_ids.get(parent_slug) if parent_slug else None
            if parent_id is not None:
                await session.exec(
                    WikiPage.__table__.update()
                    .where(WikiPage.__table__.c.id == page_ids[slug])
                    .values(parent_page_id=parent_id)
                )
        if cut_loops:
            warnings.append(f"pages_filed_under_themselves:{cut_loops}")
        if unknown:
            warnings.append(f"missing_parent_pages:{unknown}")

        if env.home_page and env.home_page in page_ids:
            wiki.home_page_id = page_ids[env.home_page]
            session.add(wiki)
        elif env.home_page:
            warnings.append("missing_home_page:1")

        await session.flush()
        return EnvelopeImportResult(
            entity_id=wiki.id,
            entity_title=wiki.name,
            created={"wikis": 1, "pages": len(env.pages), "tags": tags_created},
            matched={"tags": tags_matched},
            warnings=warnings,
        )


def _page_timestamps(page_env: WikiPageEnvelope) -> dict[str, datetime]:
    """The page's own times, where the envelope carried them.

    Returned as kwargs so an absent or unparseable stamp falls through to the
    model default rather than overwriting it — a restore that could not read a
    date is not a restore that should claim the page has none.
    """
    stamps: dict[str, datetime] = {}
    for field_name, raw in (
        ("created_at", page_env.created_at),
        ("updated_at", page_env.updated_at),
    ):
        parsed = parse_datetime(raw)
        if parsed is not None:
            stamps[field_name] = parsed
    return stamps


def _assign_slugs(pages: list[WikiPageEnvelope]) -> list[str]:
    """A slug per page, unique within this wiki and in envelope order.

    A page's slug is its address, and the table holds one address per wiki.
    An envelope from a real export already satisfies that; a hand-made one
    may not, so a repeat is suffixed rather than allowed to fail the import.
    """
    taken: set[str] = set()
    assigned: list[str] = []
    for index, page in enumerate(pages):
        base = page.slug.strip() or slugify_page_title(page.title)
        slug = base
        n = 2
        while slug in taken:
            slug = f"{base}-{n}"
            n += 1
        # Nothing usable in either the slug or the title.
        if not slug:
            slug = f"page-{index + 1}"
        taken.add(slug)
        assigned.append(slug)
    return assigned


def _parent_slugs(
    pages: list[WikiPageEnvelope], slugs: list[str]
) -> tuple[dict[str, str | None], int, int]:
    """Each page's parent slug, with anything that would not be a tree cut
    loose: a page filed under itself, a loop of pages filed under each other,
    and a parent no page in the envelope answers to. Each becomes a top-level
    page and is counted, because half a wiki filed correctly is worth more
    than a failed restore.
    """
    # The envelope names parents by their ORIGINAL slug; map those onto the
    # slugs actually assigned, which differ only where one was suffixed.
    renamed = {
        page.slug.strip(): slug for page, slug in zip(pages, slugs) if page.slug.strip()
    }
    parents: dict[str, str | None] = {}
    unknown = 0
    for page, slug in zip(pages, slugs):
        wanted = (page.parent or "").strip()
        if not wanted:
            parents[slug] = None
            continue
        resolved = renamed.get(wanted)
        if resolved is None or resolved == slug:
            parents[slug] = None
            unknown += 1
            continue
        parents[slug] = resolved

    cut_loops = 0
    for slug in list(parents):
        seen = {slug}
        walker = parents[slug]
        while walker is not None:
            if walker in seen:
                parents[slug] = None
                cut_loops += 1
                break
            seen.add(walker)
            walker = parents.get(walker)
    return parents, cut_loops, unknown
