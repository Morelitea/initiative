"""Unit tests for the Markdown → export-blocks converter."""

import pytest

from app.services.export.markdown import blocks_from_markdown

pytestmark = pytest.mark.unit


def test_empty_and_whitespace_input():
    assert blocks_from_markdown(None) == []
    assert blocks_from_markdown("") == []
    assert blocks_from_markdown("   \n  ") == []


def test_inline_formatting_runs():
    (para,) = blocks_from_markdown(
        "plain **bold** *italic* ~~strike~~ `code` [text](https://x.example)"
    )
    assert para["type"] == "paragraph"
    runs = para["runs"]
    assert {"text": "bold", "bold": True} in runs
    assert {"text": "italic", "italic": True} in runs
    assert {"text": "strike", "strike": True} in runs
    assert {"text": "code", "code": True} in runs
    assert {"text": "text", "link": "https://x.example"} in runs


def test_nested_emphasis_composes_flags():
    (para,) = blocks_from_markdown("**bold *and italic***")
    assert {"text": "and italic", "bold": True, "italic": True} in para["runs"]


def test_headings_carry_level():
    blocks = blocks_from_markdown("# One\n\n### Three")
    assert [(b["type"], b["level"]) for b in blocks] == [("heading", 1), ("heading", 3)]


def test_nested_list_structure():
    blocks = blocks_from_markdown("1. first\n2. second\n   - nested\n")
    (lst,) = blocks
    assert lst["type"] == "list" and lst["ordered"] is True
    assert lst["items"][0]["runs"] == [{"text": "first"}]
    nested = lst["items"][1]["children"][0]
    assert nested["ordered"] is False
    assert nested["items"][0]["runs"] == [{"text": "nested"}]


def test_code_block_keeps_language_and_text():
    (code,) = blocks_from_markdown("```python\nx = 1\ny = 2\n```")
    assert code == {"type": "code", "language": "python", "text": "x = 1\ny = 2"}


def test_quote_flattens_to_runs():
    (quote,) = blocks_from_markdown("> wise words\n> more words")
    assert quote["type"] == "quote"
    text = "".join(r["text"] for r in quote["runs"])
    assert "wise words" in text and "more words" in text


def test_table_rows_of_run_cells():
    (table,) = blocks_from_markdown("| A | B |\n|---|---|\n| **1** | 2 |")
    assert table["type"] == "table"
    assert table["rows"][0][0] == [{"text": "A"}]
    assert table["rows"][1][0] == [{"text": "1", "bold": True}]


def test_soft_break_is_space_and_hard_break_is_newline_run():
    """Matches the app's react-markdown defaults: a single newline renders as
    a space; a trailing-double-space hard break renders as a line break."""
    (soft,) = blocks_from_markdown("line one\nline two")
    assert {"text": "\n"} not in soft["runs"]
    (hard,) = blocks_from_markdown("line one  \nline two")
    assert {"text": "\n"} in hard["runs"]


def test_image_degrades_to_linked_alt_text():
    (para,) = blocks_from_markdown("![alt text](https://img.example/x.png)")
    assert {"text": "alt text", "link": "https://img.example/x.png"} in para["runs"]


def test_html_stays_literal_text():
    """Raw HTML must never become markup — it degrades to its literal text."""
    (para,) = blocks_from_markdown('hello <b onmouseover="x">world</b>')
    texts = "".join(r["text"] for r in para["runs"])
    assert "<b" in texts  # literal, unparsed
    assert not any(r.get("bold") for r in para["runs"])


def test_html_block_degrades_to_literal_text():
    """Block-level HTML is a leaf token — it must degrade to its literal text
    (the "never dropped" contract), not vanish because it has no children."""
    blocks = blocks_from_markdown("<details>hidden text</details>")
    assert blocks == [
        {
            "type": "paragraph",
            "runs": [{"text": "<details>hidden text</details>"}],
        }
    ]
