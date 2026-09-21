"""What an ADF document becomes, and what it admits to losing.

The degradation contract is the thing under test as much as the mapping is:
an unknown node with text keeps its words, an unknown container keeps its
children, and everything else is counted on the way out. A converter that
quietly swallows a macro is the failure this file exists to prevent.
"""

import pytest

from app.services.import_engine.adf import adf_to_markdown

pytestmark = pytest.mark.unit


def doc(*content):
    return {"version": 1, "type": "doc", "content": list(content)}


def para(*children):
    return {"type": "paragraph", "content": list(children)}


def text(value, marks=None):
    node = {"type": "text", "text": value}
    if marks:
        node["marks"] = [{"type": m} if isinstance(m, str) else m for m in marks]
    return node


# --- the ordinary shapes ---------------------------------------------------


def test_paragraphs_and_headings():
    out = adf_to_markdown(
        doc(
            {"type": "heading", "attrs": {"level": 2}, "content": [text("Title")]},
            para(text("Body text.")),
        )
    )
    assert out.markdown == "## Title\n\nBody text."
    assert out.dropped_nodes == 0


def test_a_hard_break_is_a_line_break_not_a_paragraph():
    out = adf_to_markdown(doc(para(text("one"), {"type": "hardBreak"}, text("two"))))
    assert out.markdown == "one  \ntwo"


@pytest.mark.parametrize(
    "marks,expected",
    [
        (["strong"], "**word**"),
        (["em"], "_word_"),
        (["code"], "`word`"),
        (["strike"], "~~word~~"),
        (["strong", "em"], "**_word_**"),
        (
            [{"type": "link", "attrs": {"href": "https://example.com"}}],
            "[word](https://example.com)",
        ),
        # A link wraps whatever the styling produced, not the other way round.
        (
            ["strong", {"type": "link", "attrs": {"href": "https://e.com"}}],
            "[**word**](https://e.com)",
        ),
    ],
)
def test_marks_become_markdown(marks, expected):
    out = adf_to_markdown(doc(para(text("word", marks))))
    assert out.markdown == expected
    assert out.dropped_nodes == 0


@pytest.mark.parametrize(
    "mark", ["underline", "textColor", "backgroundColor", "subsup", "alignment"]
)
def test_a_styling_mark_keeps_its_words_and_costs_nothing(mark):
    """Markdown has no underline. Losing the styling is expected; losing the
    word would not be, and neither is reporting it as a casualty."""
    out = adf_to_markdown(doc(para(text("word", [mark]))))
    assert out.markdown == "word"
    assert out.dropped_nodes == 0


def test_an_unknown_mark_keeps_its_words_and_is_counted():
    out = adf_to_markdown(doc(para(text("word", ["somethingNew"]))))
    assert out.markdown == "word"
    assert out.dropped_nodes == 1


def test_lists_nest():
    out = adf_to_markdown(
        doc(
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            para(text("outer")),
                            {
                                "type": "bulletList",
                                "content": [
                                    {
                                        "type": "listItem",
                                        "content": [para(text("inner"))],
                                    }
                                ],
                            },
                        ],
                    }
                ],
            }
        )
    )
    assert out.markdown == "- outer\n  - inner"


def test_an_ordered_list_starts_where_it_says():
    out = adf_to_markdown(
        doc(
            {
                "type": "orderedList",
                "attrs": {"order": 3},
                "content": [
                    {"type": "listItem", "content": [para(text("three"))]},
                    {"type": "listItem", "content": [para(text("four"))]},
                ],
            }
        )
    )
    assert out.markdown == "3. three\n4. four"


def test_a_code_block_keeps_its_language_and_its_asterisks():
    out = adf_to_markdown(
        doc(
            {
                "type": "codeBlock",
                "attrs": {"language": "python"},
                "content": [text("a = b * c")],
            }
        )
    )
    assert out.markdown == "```python\na = b * c\n```"


def test_a_blockquote_prefixes_its_blank_lines_too():
    """An unprefixed blank line inside a quote ends it, which would split one
    quotation into two."""
    out = adf_to_markdown(
        doc(
            {
                "type": "blockquote",
                "content": [para(text("first")), para(text("second"))],
            }
        )
    )
    assert out.markdown == "> first\n>\n> second"


def test_a_panel_says_what_kind_it_was():
    out = adf_to_markdown(
        doc(
            {
                "type": "panel",
                "attrs": {"panelType": "warning"},
                "content": [para(text("Mind the gap"))],
            }
        )
    )
    assert out.markdown == "> **Warning**\n>\n> Mind the gap"


def test_a_table_becomes_gfm_and_escapes_its_pipes():
    out = adf_to_markdown(
        doc(
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {"type": "tableHeader", "content": [para(text("A"))]},
                            {"type": "tableHeader", "content": [para(text("B"))]},
                        ],
                    },
                    {
                        "type": "tableRow",
                        "content": [
                            {"type": "tableCell", "content": [para(text("a|b"))]},
                            {"type": "tableCell", "content": [para(text("2"))]},
                        ],
                    },
                ],
            }
        )
    )
    assert out.markdown == ("| A | B |\n| --- | --- |\n| a\\|b | 2 |")


def test_a_ragged_table_is_padded_rather_than_broken():
    out = adf_to_markdown(
        doc(
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {"type": "tableHeader", "content": [para(text("A"))]},
                            {"type": "tableHeader", "content": [para(text("B"))]},
                        ],
                    },
                    {
                        "type": "tableRow",
                        "content": [
                            {"type": "tableCell", "content": [para(text("only"))]}
                        ],
                    },
                ],
            }
        )
    )
    assert out.markdown.splitlines()[-1] == "| only |  |"


def test_the_inline_oddments():
    out = adf_to_markdown(
        doc(
            para(
                {"type": "status", "attrs": {"text": "DONE"}},
                text(" "),
                {"type": "emoji", "attrs": {"text": ":smile:"}},
                text(" "),
                {"type": "date", "attrs": {"timestamp": "1709164800000"}},
                text(" "),
                {"type": "inlineCard", "attrs": {"url": "https://example.com"}},
            )
        )
    )
    assert out.markdown == (
        "**[DONE]** :smile: 2024-02-29 [https://example.com](https://example.com)"
    )


def test_layout_columns_are_read_in_sequence():
    out = adf_to_markdown(
        doc(
            {
                "type": "layoutSection",
                "content": [
                    {"type": "layoutColumn", "content": [para(text("left"))]},
                    {"type": "layoutColumn", "content": [para(text("right"))]},
                ],
            }
        )
    )
    assert out.markdown == "left\n\nright"


# --- people and pictures ---------------------------------------------------


def test_a_mention_is_a_name_until_somebody_says_who_it_is():
    node = doc(para({"type": "mention", "attrs": {"id": "abc", "text": "@Alice"}}))
    assert adf_to_markdown(node).markdown == "@Alice"

    out = adf_to_markdown(node, mention=lambda account, name: "alice#0001")
    assert out.markdown == "@[Alice](alice#0001)"


def test_an_image_is_its_filename_until_the_file_is_there():
    node = doc(
        {
            "type": "mediaSingle",
            "content": [
                {
                    "type": "media",
                    "attrs": {"id": "media-uuid", "alt": "diagram.png"},
                }
            ],
        }
    )
    # Nothing fetched it: the name is all we can honestly say.
    assert adf_to_markdown(node).markdown == "diagram.png"

    out = adf_to_markdown(node, media=lambda ident, alt: "/uploads/1/abc.png")
    assert out.markdown == "![diagram.png](/uploads/1/abc.png)"


# --- checkboxes ------------------------------------------------------------


def _task_doc():
    return doc(
        {
            "type": "taskList",
            "content": [
                {
                    "type": "taskItem",
                    "attrs": {"state": "DONE"},
                    "content": [text("packed")],
                },
                {
                    "type": "taskItem",
                    "attrs": {"state": "TODO"},
                    "content": [text("posted")],
                },
            ],
        }
    )


def test_a_description_lifts_its_tasks_into_the_checklist():
    """Where they can be ticked, rather than frozen into the body."""
    out = adf_to_markdown(_task_doc(), lift_tasks=True)
    assert out.markdown == ""
    assert [(c.text, c.done) for c in out.checklist] == [
        ("packed", True),
        ("posted", False),
    ]


def test_a_comment_keeps_its_tasks_inline():
    """A comment has no checklist to lift them into."""
    out = adf_to_markdown(_task_doc())
    assert out.markdown == "- [x] packed\n- [ ] posted"
    assert out.checklist == []


# --- the degradation contract ----------------------------------------------


def test_an_unknown_container_keeps_its_children():
    out = adf_to_markdown(
        doc({"type": "somethingNew", "content": [para(text("still here"))]})
    )
    assert out.markdown == "still here"
    assert out.dropped_nodes == 0


def test_an_unknown_leaf_with_text_keeps_its_text():
    out = adf_to_markdown(doc(para({"type": "somethingNew", "text": "words"})))
    assert out.markdown == "words"
    assert out.dropped_nodes == 0


def test_an_unknown_empty_leaf_is_dropped_and_counted():
    out = adf_to_markdown(doc({"type": "somethingNew", "attrs": {"x": 1}}))
    assert out.markdown == ""
    assert out.dropped_nodes == 1


def test_an_extension_renders_its_body_or_is_counted():
    with_body = adf_to_markdown(
        doc({"type": "bodiedExtension", "content": [para(text("macro output"))]})
    )
    assert with_body.markdown == "macro output"
    assert with_body.dropped_nodes == 0

    without = adf_to_markdown(doc({"type": "extension", "attrs": {"key": "chart"}}))
    assert without.markdown == ""
    assert without.dropped_nodes == 1


# --- somebody else's JSON --------------------------------------------------


@pytest.mark.parametrize("bad", [None, "", [], 42, {"no": "content"}])
def test_a_document_that_is_not_one_yields_nothing(bad):
    """ADF arrives over a network from a server we do not run. Every shape of
    nonsense has to be an empty document rather than an exception."""
    out = adf_to_markdown(bad)
    assert out.markdown == ""
    assert out.checklist == []


def test_a_pathological_nesting_depth_is_bounded():
    """A hostile document should cost a bounded amount of work, not a
    recursion error."""
    node = {"type": "paragraph", "content": [text("bottom")]}
    for _ in range(200):
        node = {"type": "blockquote", "content": [node]}
    out = adf_to_markdown(doc(node))
    assert isinstance(out.markdown, str)


def test_content_that_is_not_a_list_is_survivable():
    out = adf_to_markdown({"type": "doc", "content": "not a list"})
    assert out.markdown == ""
