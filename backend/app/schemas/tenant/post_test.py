"""What a post reads as in one line.

Every surface that lists notices without rendering them — recents, search, the
guild-wide table, the board's own cards — shows the excerpt, so what counts as
a word and where the line is cut is the whole of it.
"""

from app.schemas.tenant.post import post_excerpt


def test_excerpt_reads_every_kind_of_text_node():
    """Chips keep their words in ``text`` like a text node, so the excerpt
    reads what the post says rather than only its plain runs. A mention of
    somebody reads as its markdown, which the client names; one with no
    account as the name it has."""
    body = {
        "root": {
            "children": [
                {
                    "type": "paragraph",
                    "children": [
                        {"type": "text", "text": "Ping"},
                        {"type": "mention", "mentionUserId": 42, "text": "Ada"},
                        {"type": "mention", "mentionUserId": None, "text": "Bo"},
                        {"type": "text", "text": "about"},
                        {"type": "smart-chip", "text": "Ship it"},
                    ],
                }
            ]
        }
    }
    assert post_excerpt(body) == "Ping @[](42) Bo about Ship it"


def test_excerpt_of_a_body_with_no_words_is_empty():
    """A notice that is only a picture has nothing to excerpt — it shows as its
    headline, which is what there is."""
    body = {"root": {"children": [{"type": "image", "src": "/x.png"}]}}
    assert post_excerpt(body) == ""
    assert post_excerpt({}) == ""


def test_excerpt_truncates_on_a_word_boundary():
    body = {
        "root": {
            "children": [
                {
                    "type": "paragraph",
                    "children": [{"type": "text", "text": "wo " * 200}],
                }
            ]
        }
    }
    excerpt = post_excerpt(body, limit=20)
    assert len(excerpt) <= 20
    assert excerpt.endswith("…")
    assert not excerpt.endswith("w…")
    # A mention the cut goes through is left out whole.
    cut = {
        "root": {
            "children": [
                {
                    "type": "paragraph",
                    "children": [
                        {"type": "text", "text": "wo"},
                        {"type": "mention", "mentionUserId": 4242424242, "text": ""},
                    ],
                }
            ]
        }
    }
    assert post_excerpt(cut, limit=12) == "wo …"
