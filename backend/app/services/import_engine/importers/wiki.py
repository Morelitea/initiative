"""``initiative-wiki`` importer: the wiki row, its pages, the shape they sit
in, and the tags on both.

The tree arrives as slugs. Pages are written into the envelope in the order
the navigation draws them — siblings by position, not a walk down each branch
— so a child can appear before its parent. Every page is therefore created
first and filed second, once the whole slug map exists.

Sharing does not cross, here or in any other envelope: who may read a wiki is
a fact about the community it was written in. The importer owns what it
creates.

A page can name people — who wrote it, and anybody its body mentions — and
other pages, by slug. Those are placed once every page exists: a writer the
people step placed becomes the page's author, a mention of somebody placed
links to them, and a mention of a page links to the page it became.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.wiki import Wiki, WikiPage
from app.schemas.tenant.import_envelopes import WikiEnvelope, WikiPageEnvelope
from app.services.import_engine.common import (
    ensure_tag,
    handle_key,
    load_initiative_member_handles,
    parse_datetime,
    unique_name,
)
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.context import ImportContext
from app.services.import_engine.importers._base import (
    grant_ownership,
    parse_envelope,
)
from app.services.import_engine.people import PeopleMap, quoted_account
from app.services.tenant import tags as tags_service
from app.services.tenant.wikis import slugify_page_title

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.schemas.tenant.backup_export import ManifestPerson


class WikiImporter:
    envelope_type = "initiative-wiki"
    permission = PermissionKey.create_wikis

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(WikiEnvelope, envelope)

    def people(self, validated: BaseModel) -> list["ManifestPerson"]:
        """Whoever wrote a page, and whoever a page mentions, most-named
        first — both are placed through the people step's answer."""
        from app.schemas.tenant.backup_export import ManifestPerson

        envelope: WikiEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        seen: dict[str, ManifestPerson] = {}
        counts: dict[str, int] = {}
        for page in envelope.pages:
            named = [
                (page.author_handle, page.author_name),
                *((handle, None) for handle in page.mention_handles),
            ]
            for handle, name in named:
                handle = (handle or "").strip()
                if not handle:
                    continue
                key = handle_key(handle)
                counts[key] = counts.get(key, 0) + 1
                person = seen.setdefault(
                    key, ManifestPerson(handle=handle, name=name, comment_count=0)
                )
                if person.name is None:
                    person.name = name
        return sorted(
            seen.values(),
            key=lambda p: (-counts[handle_key(p.handle)], p.handle.lower()),
        )

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
                resolved = await ensure_tag(session, name=tag_name, color="#6b7280")
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

        people = context.people if context is not None else PeopleMap()
        member_handles = (
            await load_initiative_member_handles(
                session, initiative_id=target_initiative.id
            )
            if any(p.author_handle or p.mention_handles for p in env.pages)
            else {}
        )

        # Pass one: every page exists before any page is filed.
        slugs = _assign_slugs(env.pages)
        page_ids: dict[str, int] = {}
        rows: list[WikiPage] = []
        for page_env, slug in zip(env.pages, slugs):
            author = quoted_account(
                page_env.author_handle, people=people, member_handles=member_handles
            )
            row = WikiPage(
                wiki_id=wiki.id,
                title=page_env.title,
                slug=slug,
                position=page_env.position,
                is_draft=page_env.is_draft,
                content=page_env.content or {},
                created_by=author if author is not None else importer.id,
                # When it was written, where the envelope says so. Absent
                # leaves the model's own default — the moment of the import,
                # which is the only time this row can honestly claim.
                **_page_timestamps(page_env),
            )
            session.add(row)
            await session.flush()
            page_ids[slug] = row.id  # ty: ignore[invalid-assignment] — persisted row, id is set
            rows.append(row)
            if context is not None:
                context.links.register(
                    page_env.external_ref, SearchEntityType.wiki_page, row.id
                )
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

        # Pass three: what a page names, now that every page has an id.
        wanted = {key for page in env.pages for key in _jira_keys(page.content)}
        # An issue that came over in this same import is already known by the
        # ref its task was registered under; anything else is looked up by
        # the key an earlier Jira import recorded.
        jira_tasks: dict[str, int] = {}
        if context is not None:
            for key in wanted:
                endpoint = context.links.lookup(f"jira:{key}")
                if endpoint is not None and endpoint.kind == SearchEntityType.task:
                    jira_tasks[key] = endpoint.id
        jira_tasks.update(await _tasks_by_jira_key(session, wanted - jira_tasks.keys()))
        # A file the pages link to was written earlier in this job, as a
        # document of its own.
        documents: dict[str, int] = {}
        if context is not None:
            for ref in {
                r for page in env.pages for r in _marks(page.content, "importRef")
            }:
                endpoint = context.links.lookup(ref)
                if endpoint is not None and endpoint.kind == SearchEntityType.document:
                    documents[ref] = endpoint.id
        by_original = {page.slug.strip(): slug for page, slug in zip(env.pages, slugs)}
        for page_env, row in zip(env.pages, rows):
            mentioned = {
                handle: account
                for handle in page_env.mention_handles
                if (
                    account := quoted_account(
                        handle, people=people, member_handles=member_handles
                    )
                )
                is not None
            }
            linked = _place_references(
                row.content,
                page_ids={
                    original: page_ids[assigned]
                    for original, assigned in by_original.items()
                    if assigned in page_ids
                },
                mentioned=mentioned,
                jira_tasks=jira_tasks,
                documents=documents,
            )
            if linked is not None:
                row.content = linked
                session.add(row)

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


def _text_node(text: str) -> dict[str, Any]:
    return {
        "type": "text",
        "version": 1,
        "text": text,
        "format": 0,
        "style": "",
        "mode": "normal",
        "detail": 0,
    }


def _marks(content: Any, name: str) -> set[str]:
    """Every value of one import placeholder a page's content carries."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        value = node.get(name)
        if isinstance(value, str) and value:
            found.add(value)
        for child in node.get("children") or []:
            walk(child)

    walk(content.get("root") if isinstance(content, dict) else None)
    return found


def _jira_keys(content: Any) -> set[str]:
    """The Jira issue keys a page's content waits to have placed."""
    return _marks(content, "importJiraKey")


async def _tasks_by_jira_key(session: AsyncSession, keys: set[str]) -> dict[str, int]:
    """Which task each Jira issue became, found by the key the Jira import
    records on every task it writes.

    Anywhere in the community this person can read — a Confluence space and
    the Jira project its pages talk about are often filed in different
    initiatives. An issue imported twice points at the newer copy. An issue
    whose key property was left out at import, or that never came over, is
    not found, and the page keeps its link to Jira.
    """
    if not keys:
        return {}
    from sqlalchemy import or_

    from app.models.tenant.property import PropertyDefinition, TaskPropertyValue
    from app.models.tenant.task import Task
    from app.services.import_engine.jira_fields import JIRA_KEY_PROPERTY

    rows = (
        await session.exec(
            select(TaskPropertyValue.value_text, Task.id)
            .join(
                PropertyDefinition,
                PropertyDefinition.id == TaskPropertyValue.property_id,
            )
            .join(Task, Task.id == TaskPropertyValue.task_id)
            .where(
                # The name the import gave it, or the one it was renamed to
                # when that name was already taken by a different kind.
                or_(
                    PropertyDefinition.name == JIRA_KEY_PROPERTY,
                    PropertyDefinition.name.like(f"{JIRA_KEY_PROPERTY} (%"),
                ),
                TaskPropertyValue.value_text.in_(sorted(keys)),
                Task.deleted_at.is_(None),
            )
            .order_by(Task.id)
        )
    ).all()
    found: dict[str, int] = {}
    for key, task_id in rows:
        if key is not None and task_id is not None:
            found[key] = task_id
    return found


def _place_references(
    content: Any,
    *,
    page_ids: dict[str, int],
    mentioned: dict[str, int],
    jira_tasks: dict[str, int] | None = None,
    documents: dict[str, int] | None = None,
) -> dict[str, Any] | None:
    """``content`` with its import references resolved, or ``None`` if it
    had none.

    A wiki-page mention carrying an ``importSlug`` points at the page that
    slug became; one whose page did not arrive is its text again. A person's
    mention with no account yet gets the one the people step placed its name
    on, and stays a name otherwise.

    A Jira issue the page names by ``importJiraKey`` points at the task that
    issue became, when it came over: the macro's mention and its live status
    chip take the task's id, and a link to the issue becomes a mention of the
    task. When it did not, the mention is a link back to Jira again, the chip
    is left out, and a link stays the link it was.

    A document mention carrying an ``importRef`` points at the document that
    file became in this job, and is the file's name again if it did not.
    """
    if not isinstance(content, dict):
        return None
    tasks = jira_tasks or {}
    files = documents or {}
    changed = False

    def walk(node: Any) -> Any:
        nonlocal changed
        if not isinstance(node, dict):
            return node
        node_type = node.get("type")
        if node_type == "entity-mention" and "importSlug" in node:
            changed = True
            slug = node.get("importSlug")
            target = page_ids.get(slug) if isinstance(slug, str) else None
            text = str(node.get("text") or "")
            if target is None:
                return _text_node(text)
            placed = {k: v for k, v in node.items() if k != "importSlug"}
            placed["entityId"] = target
            return placed
        if node_type == "entity-mention" and "importRef" in node:
            changed = True
            ref = node.get("importRef")
            document_id = files.get(ref) if isinstance(ref, str) else None
            if document_id is None:
                return _text_node(str(node.get("text") or ""))
            placed = {k: v for k, v in node.items() if k != "importRef"}
            placed["entityId"] = document_id
            return placed
        jira_key = node.get("importJiraKey")
        if isinstance(jira_key, str):
            changed = True
            task_id = tasks.get(jira_key)
            bare = {
                k: v for k, v in node.items() if k not in ("importJiraKey", "importUrl")
            }
            if node_type == "entity-mention":
                if task_id is not None:
                    return {**bare, "entityId": task_id}
                url = node.get("importUrl")
                text = str(node.get("text") or jira_key)
                if not isinstance(url, str) or not url:
                    return _text_node(text)
                return {
                    "type": "link",
                    "version": 1,
                    "direction": "ltr",
                    "format": "",
                    "indent": 0,
                    "url": url,
                    "rel": "noopener noreferrer",
                    "target": "_blank",
                    "title": None,
                    "children": [_text_node(text)],
                }
            if node_type == "smart-chip":
                return {**bare, "entityId": task_id} if task_id is not None else None
            if node_type == "link" and task_id is not None:
                words = "".join(
                    str(child.get("text") or "")
                    for child in node.get("children") or []
                    if isinstance(child, dict)
                )
                return {
                    "type": "entity-mention",
                    "version": 1,
                    "entityType": "task",
                    "entityId": task_id,
                    "text": words or jira_key,
                }
            node = bare
        if (
            node_type == "mention"
            and node.get("mentionUserId") is None
            and node.get("mentionName") in mentioned
        ):
            changed = True
            return {**node, "mentionUserId": mentioned[node["mentionName"]]}
        children = node.get("children")
        if isinstance(children, list):
            walked = [walk(child) for child in children]
            return {
                **node,
                "children": [child for child in walked if child is not None],
            }
        return node

    placed = walk(content.get("root"))
    if not changed:
        return None
    return {**content, "root": placed}


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
