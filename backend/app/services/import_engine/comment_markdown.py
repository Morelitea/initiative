"""An editor state as the text of a comment.

A comment is Markdown with its own way of naming people and things —
``@[Sam Bee](42)`` and ``#task[Fix the bug](12)`` — so a body that arrived as
an editor state (a Confluence comment, converted the way a page is) is
rendered here once its references have been placed. The rendering is the
Markdown export's, so a list, a table or a code block reads the same way it
does in a downloaded document.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services.export.lexical import _markdown_text, blocks_from_editor_state

#: No guild's uploads are this one's, so every picture keeps its own address
#: rather than being rewritten as a file inside an export archive.
_NO_ARCHIVE = -1


def comment_markdown(content: Any) -> str:
    """The comment text for a placed editor state, or ``""`` for none."""
    if not isinstance(content, dict):
        return ""
    state = deepcopy(content)
    root = state.get("root")
    if not isinstance(root, dict):
        return ""
    state["root"] = _inline_references(root)
    blocks, _assets = blocks_from_editor_state(state, guild_id=_NO_ARCHIVE)
    if not blocks:
        return ""
    return _markdown_text({"blocks": blocks}).strip()


def _text(text: str, node: dict[str, Any]) -> dict[str, Any]:
    return {"type": "text", "text": text, "format": node.get("format") or 0}


def _inline_references(node: Any) -> Any:
    """Each placed reference as the words a comment writes it with."""
    if not isinstance(node, dict):
        return node
    kind = node.get("type")
    if kind == "mention":
        name = str(node.get("mentionName") or node.get("text") or "").lstrip("@")
        user_id = node.get("mentionUserId")
        label = name.replace("[", "").replace("]", "")
        if isinstance(user_id, int) and not isinstance(user_id, bool):
            return _text(f"@[{label}]({user_id})", node)
        return _text(f"@{name}", node)
    if kind == "entity-mention":
        text = str(node.get("text") or "")
        entity_id = node.get("entityId")
        entity_type = node.get("entityType")
        if isinstance(entity_id, int) and entity_id > 0 and entity_type:
            label = text.replace("[", "").replace("]", "")
            return _text(f"#{entity_type}[{label}]({entity_id})", node)
        return _text(text, node)
    if kind == "smart-chip":
        # A live status belongs beside the thing it reads; in a comment the
        # reference before it already names that thing.
        return None
    children = node.get("children")
    if isinstance(children, list):
        placed = [_inline_references(child) for child in children]
        return {**node, "children": [child for child in placed if child is not None]}
    return node
