"""Markdown → export blocks.

Task (and project/initiative) descriptions are Markdown — the web UI renders
them with react-markdown + GFM — so a PDF that prints the raw source shows
``**bold**`` literally. This module parses that Markdown (CommonMark plus the
GFM strikethrough/table extensions markdown-it ships) into the same JSON-safe
blocks/runs intermediate the Lexical converter emits, so the Typst templates
render both through one vocabulary:

* ``paragraph``/``heading``/``quote`` — ``runs`` of ``{text, bold, italic,
  strike, code, link}``; hard breaks are ``{"text": "\\n"}`` runs (softbreaks
  collapse to a space, matching react-markdown's default).
* ``list`` — ``ordered`` flag and ``items`` of ``{runs, children}`` (nested
  lists recurse), ``checklist`` always false (GFM task-list markers need a
  plugin; they stay literal text, same as unsupported syntax anywhere).
* ``code`` — fenced/indented blocks with the info string as ``language``.
* ``table`` — rows of cells, each cell a runs list.
* ``hr``.

Unknown/unsupported nodes degrade to their text content — never dropped,
never markup."""

from __future__ import annotations

from typing import Any

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

_parser = MarkdownIt("commonmark").enable(["strikethrough", "table"])

_HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


def blocks_from_markdown(text: str | None) -> list[dict[str, Any]]:
    """Parse Markdown into export blocks; empty/whitespace input → []."""
    if not text or not text.strip():
        return []
    tree = SyntaxTreeNode(_parser.parse(text))
    return _blocks(tree)


def _blocks(parent: SyntaxTreeNode) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in parent.children:
        kind = node.type
        if kind == "paragraph":
            runs = _inline_runs(node)
            if runs:
                out.append({"type": "paragraph", "runs": runs})
        elif kind == "heading":
            out.append(
                {
                    "type": "heading",
                    "level": _HEADING_LEVELS.get(node.tag, 1),
                    "runs": _inline_runs(node),
                }
            )
        elif kind in ("bullet_list", "ordered_list"):
            out.append(_list_block(node))
        elif kind == "blockquote":
            # Flatten the quote's inner blocks into one runs stream (paragraph
            # boundaries become hard breaks) — the templates render quotes as
            # a single styled block, mirroring the Lexical converter.
            runs: list[dict[str, Any]] = []
            for i, inner in enumerate(_blocks(node)):
                if i > 0:
                    runs.append({"text": "\n"})
                runs.extend(inner.get("runs") or [{"text": inner.get("text", "")}])
            out.append({"type": "quote", "runs": runs})
        elif kind in ("fence", "code_block"):
            out.append(
                {
                    "type": "code",
                    "language": (node.info or "").strip().split(" ")[0]
                    if kind == "fence"
                    else "",
                    "text": node.content.rstrip("\n"),
                }
            )
        elif kind == "hr":
            out.append({"type": "hr"})
        elif kind == "table":
            out.append({"type": "table", "rows": _table_rows(node)})
        else:
            # Unknown container: recurse so its content still exports.
            out.extend(_blocks(node))
    return out


def _list_block(node: SyntaxTreeNode) -> dict[str, Any]:
    items = []
    for item in node.children:  # list_item nodes
        runs: list[dict[str, Any]] = []
        children: list[dict[str, Any]] = []
        for part in item.children:
            if part.type in ("bullet_list", "ordered_list"):
                children.append(_list_block(part))
            elif part.type in ("paragraph", "inline"):
                if runs:
                    runs.append({"text": "\n"})
                runs.extend(_inline_runs(part))
            else:
                # Block content inside an item (code, quote…): degrade to text.
                if runs:
                    runs.append({"text": "\n"})
                runs.append({"text": part.content})
        entry: dict[str, Any] = {"runs": runs}
        if children:
            entry["children"] = children
        items.append(entry)
    return {
        "type": "list",
        "ordered": node.type == "ordered_list",
        "checklist": False,
        "items": items,
    }


def _table_rows(node: SyntaxTreeNode) -> list[list[list[dict[str, Any]]]]:
    rows: list[list[list[dict[str, Any]]]] = []
    for section in node.children:  # thead / tbody
        for tr in section.children:
            rows.append([_inline_runs(cell) for cell in tr.children])
    return rows


def _inline_runs(node: SyntaxTreeNode) -> list[dict[str, Any]]:
    """Collect a block node's inline content as runs."""
    inline = next((c for c in node.children if c.type == "inline"), None)
    target = inline if inline is not None else node
    return _runs(target, frozenset(), None)


def _runs(
    node: SyntaxTreeNode, flags: frozenset[str], link: str | None
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for child in node.children:
        kind = child.type
        if kind == "text":
            if child.content:
                runs.append(_run(child.content, flags, link))
        elif kind == "code_inline":
            runs.append(_run(child.content, flags | {"code"}, link))
        elif kind == "strong":
            runs.extend(_runs(child, flags | {"bold"}, link))
        elif kind == "em":
            runs.extend(_runs(child, flags | {"italic"}, link))
        elif kind == "s":
            runs.extend(_runs(child, flags | {"strike"}, link))
        elif kind == "link":
            href = str(child.attrs.get("href") or "") or link
            runs.extend(_runs(child, flags, href))
        elif kind == "softbreak":
            # react-markdown's default: a soft break renders as a space.
            runs.append(_run(" ", flags, link))
        elif kind == "hardbreak":
            runs.append({"text": "\n"})
        elif kind == "image":
            # No fetching in a description render: degrade to the alt text
            # linked to the source URL.
            alt = child.content or str(child.attrs.get("alt") or "") or "[image]"
            src = str(child.attrs.get("src") or "")
            runs.append(_run(alt, flags, src or link))
        elif kind == "html_inline":
            runs.append(_run(child.content, flags, link))  # literal, not markup
        elif child.children:
            runs.extend(_runs(child, flags, link))
        elif child.content:
            runs.append(_run(child.content, flags, link))
    return runs


def _run(text: str, flags: frozenset[str], link: str | None) -> dict[str, Any]:
    run: dict[str, Any] = {"text": text}
    for flag in flags:
        run[flag] = True
    if link:
        run["link"] = link
    return run
