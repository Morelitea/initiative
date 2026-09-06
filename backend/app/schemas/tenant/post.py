from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pydantic import ConfigDict, Field, model_validator

from app.schemas.base import SanitizedBaseModel, TitleStr
from app.schemas.tenant.reaction import ReactionGroup
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.schemas.tenant.tag import TagSummary, tag_summaries

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.post import Post


# How much of a post the one-line surfaces get. Long enough to tell two
# notices apart in a recents tab, short enough that a list of them stays a
# list.
EXCERPT_CHARS = 280

# How long a notice may be. A board is read, not studied: this is roughly
# 1,500 words, which is far more than any notice needs and still short enough
# that a page of twenty stays a page. Something longer is a document, and the
# initiative already has those.
MAX_POST_TEXT_CHARS = 10_000

# A structural ceiling on the stored state, independent of how much of it is
# words. Images and files are references rather than embedded data, so a
# legitimate notice is nowhere near this; it is here so a hand-made payload of
# deeply nested empty nodes cannot be stored at all.
MAX_POST_BODY_BYTES = 256 * 1024


class PostBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class PostCreate(PostBase):
    name: TitleStr = Field(..., min_length=1, max_length=255)
    initiative_id: int
    # A Lexical editor state, the same shape a native document stores — which
    # is what lets a post carry inline images and smart chips. Empty is
    # allowed: a headline with a picture under it is a legitimate notice.
    body: Dict[str, Any] = Field(default_factory=dict)
    tag_ids: Optional[List[int]] = None
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    # A board notice defaults to readable by the whole initiative, which is the
    # point of posting it.
    grants: List[ResourceGrantSchema] = Field(
        default_factory=lambda: [
            ResourceGrantSchema(all_initiative_members=True, level="read")
        ]
    )


class PostUpdate(SanitizedBaseModel):
    name: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    body: Optional[Dict[str, Any]] = None


class PostPinUpdate(SanitizedBaseModel):
    """Pin or unpin one post. ``pinned`` false clears the expiry with it —
    an expiry belongs to a pin, and keeping a stale one around would silently
    apply to the next pin."""

    pinned: bool = True
    #: Optional; when set the pin lapses at this instant and the post falls
    #: back into the feed by date. Must be in the future.
    expires_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_expiry(self) -> "PostPinUpdate":
        if not self.pinned and self.expires_at is not None:
            raise ValueError("An expiry only means something on a pin")
        return self


class PostSummary(PostBase):
    """A post without its body — for the surfaces that show one in a line.

    The board is not one of them: it renders notices, so its list returns
    :class:`PostRead`. This shape is for the guild-wide table, recents, and
    anywhere else a post is a row rather than a thing being read.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    initiative_id: int
    guild_id: int
    created_by: int
    created_at: datetime
    updated_at: datetime
    #: The first line or so of the body as plain text. Derived on the way out,
    #: never stored — the body is the truth, and a stored copy would go stale
    #: the first time somebody edited it.
    excerpt: str = ""
    pinned_at: Optional[datetime] = None
    pinned_by: Optional[int] = None
    pin_expires_at: Optional[datetime] = None
    #: Whether the pin above is in force *right now*. Served rather than
    #: recomputed client-side so the board and the API agree on the boundary
    #: case of an expiry that has just passed.
    is_pinned: bool = False
    my_permission_level: Optional[str] = None
    # Advanced setting: when true this entity's comment thread is off — the
    # UI renders none and the API refuses to read or post one.
    comments_disabled: bool = False
    #: How many comments the post has. Served with the board so a reader can
    #: see there is a conversation without opening the post to find out — and
    #: so an empty thread can invite the first one.
    comment_count: int = 0
    tags: List[TagSummary] = Field(default_factory=list)
    grants: List[ResourceGrantSchema] = Field(default_factory=list)
    #: Reactions ride along with the post rather than costing a request per
    #: row: a board renders its chips from the one list call.
    reactions: List[ReactionGroup] = Field(default_factory=list)


class PostRead(PostSummary):
    #: The Lexical editor state. Present on the board list too, because a board
    #: renders its notices rather than a table of headlines — which is why that
    #: list pages small.
    body: Dict[str, Any] = Field(default_factory=dict)


class PostListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[PostRead]
    total_count: int
    page: int
    page_size: int
    has_next: bool


def post_text(body: Any) -> str:
    """The words in a Lexical editor state, whitespace-collapsed.

    Walks every node collecting ``text``, which is where a text node, a
    mention and a smart chip's label all keep their words — the same field the
    search extractor reads in SQL, so a post reads the same way in a search
    result, in a recents tab, and to the length check. Anything with no words
    of its own (an image, a divider) contributes nothing rather than a
    placeholder.
    """
    parts: list[str] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        text = node.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                walk(child)

    if isinstance(body, dict):
        walk(body.get("root"))

    return " ".join(" ".join(parts).split())


def post_body_too_long(body: Any) -> bool:
    """Whether a body breaks either ceiling a post is held to.

    THE rule, in one place, because there are two ways in — the endpoints and
    an import — and they were allowed to disagree once already: the envelope
    checked the character count and let a large, low-text Lexical structure
    through, which the endpoints would then refuse to save again.

    Two ceilings because they answer different questions. The character count
    is the product rule — a board is read, not studied, and something this long
    is a document. The byte size is structural, and independent of how much of
    it is words: images and files are references rather than embedded data, so
    a legitimate notice is nowhere near it and only a hand-made payload of
    deeply nested empty nodes trips it.
    """
    import json

    clean = body or {}
    if len(post_text(clean)) > MAX_POST_TEXT_CHARS:
        return True
    return len(json.dumps(clean).encode("utf-8")) > MAX_POST_BODY_BYTES


def post_excerpt(body: Any, *, limit: int = EXCERPT_CHARS) -> str:
    """The first line or so of a post, for the surfaces that show one in a
    line — recents, search, the guild table."""
    joined = post_text(body)
    if len(joined) <= limit:
        return joined
    # Cut on a word boundary where there is one nearby, so the excerpt does not
    # end mid-word.
    cut = joined[: limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut + "…"


def serialize_post_summary(
    post: "Post", *, user_id: Optional[int] = None
) -> PostSummary:
    # Local import avoids a schema -> service import cycle.
    from app.services.permissions import compute_post_permission, serialize_grants
    from app.services.tenant import reactions as reactions_service

    reaction_rows = getattr(post, "_reactions", None)

    return PostSummary(
        id=post.id,
        name=post.name,
        initiative_id=post.initiative_id,
        guild_id=post.guild_id,
        created_by=post.created_by,
        created_at=post.created_at,
        updated_at=post.updated_at,
        excerpt=post_excerpt(post.body),
        pinned_at=post.pinned_at,
        pinned_by=post.pinned_by,
        pin_expires_at=post.pin_expires_at,
        is_pinned=post.is_pinned_now(),
        my_permission_level=(
            compute_post_permission(post, user_id) if user_id is not None else None
        ),
        comments_disabled=post.comments_disabled,
        comment_count=getattr(post, "comment_count", 0),
        tags=tag_summaries(getattr(post, "tag_links", None)),
        grants=serialize_grants(post),
        reactions=(
            reactions_service.summarize(reaction_rows, viewer_id=user_id)
            if reaction_rows
            else []
        ),
    )


def serialize_post(post: "Post", *, user_id: Optional[int] = None) -> PostRead:
    summary = serialize_post_summary(post, user_id=user_id)
    return PostRead(**summary.model_dump(), body=post.body or {})
