"""Base schema with automatic HTML sanitization for str fields."""

from __future__ import annotations

import html
from enum import Enum
from functools import lru_cache
from typing import Annotated, Any, get_args, get_origin, get_type_hints

import nh3
from pydantic import BaseModel, model_validator

# Hard ceiling on any plain-text field. Generous for names/titles/labels/tokens
# while bounding both the stored size (DoS) and the entity-decode loop in
# _strip_to_plain_text. Fields that legitimately hold large data (base64 images,
# import payloads, AI output) opt out via RawTextStr; rich text via RichTextStr.
MAX_PLAIN_TEXT_LENGTH = 8192


class _SanitizeOptOut:
    """Base for markers that exempt a field from plain-text sanitization."""


class _RichTextMarker(_SanitizeOptOut):
    """Marker: field holds rich text rendered as markup — keep raw input."""


class _RawTextMarker(_SanitizeOptOut):
    """Marker: field holds raw/opaque data validated elsewhere (base64, import
    payloads, tokens) — keep raw input and skip the length cap."""


RichTextStr = Annotated[str, _RichTextMarker()]
"""str that opts out of plain-text sanitization (rich text kept verbatim)."""

RawTextStr = Annotated[str, _RawTextMarker()]
"""str that opts out of sanitization AND the length cap (large/opaque data)."""


def _strip_to_plain_text(value: str) -> str:
    """Strip all HTML markup from a plain-text field WITHOUT HTML-encoding it.

    ``nh3.clean()`` is an HTML *output encoder*: it turns ``&`` into ``&amp;``,
    ``<`` into ``&lt;`` and so on, producing a string that is safe to drop into
    raw HTML. That is wrong for plain-text fields (names, titles, labels): the
    frontend renders them as React text nodes, which escape for the DOM at
    render time, so a stored ``&amp;`` shows up literally on screen as the four
    characters ``&amp;`` instead of ``&``.

    For these fields we want dangerous markup gone (``<img onerror>``,
    ``<script>``) but the benign characters the user actually typed (``&``,
    ``<``, ``>``, ``"``) preserved verbatim.

    The subtlety: a naive ``html.unescape(nh3.clean(value))`` unescapes *after*
    stripping, so an already-entity-encoded payload (``&lt;img onerror&gt;``)
    sails past ``nh3.clean`` as inert text and is then revived into live markup
    by the unescape. So we fully decode the input *first* — to a fixpoint, so
    markup encoded to any depth (``&amp;lt;…``) is exposed — and only then strip.
    Stripping with an empty allowlist also removes tags nh3's default allowlist
    would keep (e.g. ``<img src="x">``), which is what a plain-text field wants.
    """
    # Decode to a fixpoint before stripping. html.unescape returns a strictly
    # shorter string whenever it changes anything, so this terminates on its own
    # (no arbitrary iteration cap): worst case is one pass per entity.
    decoded = value
    while (once := html.unescape(decoded)) != decoded:
        decoded = once
    # Strip every tag, then undo the encoding nh3 applies to the surviving benign
    # characters. The final unescape is tag-free: ``decoded`` holds no entities,
    # so nh3 only ``&``-encodes lone </>/& that were never part of a tag.
    return html.unescape(nh3.clean(decoded, tags=set(), attributes={}))


def _annotation_has_opt_out(annotation: Any) -> bool:
    """True if a sanitization opt-out marker appears anywhere in the annotation,
    including nested inside ``Optional[...]`` / ``Union[...]``."""
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        if any(isinstance(m, _SanitizeOptOut) for m in args[1:]):
            return True
        return _annotation_has_opt_out(args[0])
    if get_origin(annotation) is not None:
        return any(_annotation_has_opt_out(a) for a in get_args(annotation))
    return False


@lru_cache(maxsize=None)
def _opt_out_fields(cls: type) -> frozenset[str]:
    """Field names exempt from sanitization (RichTextStr/RawTextStr), resolved
    once per model. ``field_info.metadata`` only carries *top-level* Annotated
    metadata, so a marker nested in ``Optional[...]`` is invisible there — we
    walk the resolved annotations instead. Falls back to the top-level metadata
    if the annotations can't be introspected (e.g. an unresolved forward ref)."""
    try:
        hints = get_type_hints(cls, include_extras=True)
    except Exception:
        return frozenset(
            name
            for name, fi in cls.model_fields.items()
            if any(isinstance(m, _SanitizeOptOut) for m in fi.metadata)
        )
    return frozenset(
        name
        for name in cls.model_fields
        if name in hints and _annotation_has_opt_out(hints[name])
    )


def _is_enum_type(annotation: Any) -> bool:
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return True
    # Handle Optional[SomeEnum], Union[SomeEnum, None], etc.
    args = getattr(annotation, "__args__", None)
    if args:
        return any(isinstance(a, type) and issubclass(a, Enum) for a in args)
    return False


class SanitizedBaseModel(BaseModel):
    """BaseModel that strips HTML markup from every str field by default.

    Plain-text fields have all tags removed without HTML-encoding the surviving
    characters, so ``Foo & Bar`` stays ``Foo & Bar`` (not ``Foo &amp; Bar``)
    while ``<img onerror>``/``<script>`` payloads are stripped — see
    :func:`_strip_to_plain_text` — and are rejected past
    :data:`MAX_PLAIN_TEXT_LENGTH` characters. Fields typed :data:`RichTextStr`
    (rich text) or :data:`RawTextStr` (large or opaque data) opt out of both,
    even when wrapped in ``Optional[...]``. Enum-typed fields are skipped.
    """

    @model_validator(mode="before")
    @classmethod
    def _sanitize_strings(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        exempt = _opt_out_fields(cls)
        for field_name, field_info in cls.model_fields.items():
            if field_name in exempt:
                continue
            if _is_enum_type(field_info.annotation):
                continue
            value = data.get(field_name)
            if isinstance(value, str):
                if len(value) > MAX_PLAIN_TEXT_LENGTH:
                    raise ValueError(
                        f"{field_name} exceeds the maximum length of "
                        f"{MAX_PLAIN_TEXT_LENGTH} characters"
                    )
                data[field_name] = _strip_to_plain_text(value)
        return data
