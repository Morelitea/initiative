"""The document editor on the server: a state read back is the document
written, and a room can hold it."""

import pytest
from pycrdt import Doc

from app.services import editor_engine
from app.services.editor_engine import EditorError

# The editor is built from frontend/, which test selection cannot see.
pytestmark = pytest.mark.always

_ELEMENT = {"direction": "ltr", "format": "", "indent": 0, "version": 1}


def _text(text: str, format: int = 0) -> dict:
    return {"type": "text", "text": text, "format": format, "version": 1}


def _paragraph(*children: dict) -> dict:
    return {"type": "paragraph", "children": list(children), **_ELEMENT}


def _document(*blocks: dict) -> dict:
    return {"root": {"type": "root", "children": list(blocks), **_ELEMENT}}


def _without_defaults(value):
    """A document as it reads, whichever way it spells a default."""
    if isinstance(value, dict):
        return {
            key: _without_defaults(item)
            for key, item in value.items()
            if item not in (0, "", None, False, "normal") or item is True
        }
    if isinstance(value, list):
        return [_without_defaults(item) for item in value]
    return value


DOCUMENT = _document(
    {"type": "heading", "tag": "h1", "children": [_text("Title")], **_ELEMENT},
    _paragraph(
        _text("Plain, "),
        _text("bold", 1),
        {
            "type": "link",
            "url": "https://example.com",
            "children": [_text("a link")],
            **_ELEMENT,
        },
    ),
    {
        "type": "list",
        "listType": "check",
        "start": 1,
        "tag": "ul",
        "children": [
            {
                "type": "listitem",
                "value": 1,
                "checked": True,
                "children": [_text("done")],
                **_ELEMENT,
            }
        ],
        **_ELEMENT,
    },
    {
        "type": "callout",
        "variant": "info",
        "collapsed": False,
        "children": [_paragraph(_text("Inside a callout"))],
        **_ELEMENT,
    },
    _paragraph({"type": "mention", "mentionUserId": 7, "version": 1}),
    {"type": "quote", "children": [_text("A quote")], **_ELEMENT},
    # Highlighted into tokens, as the browser stores it.
    {
        "type": "code",
        "language": "python",
        "children": [
            {**_text("print"), "type": "code-highlight", "highlightType": "keyword"},
            {**_text("("), "type": "code-highlight", "highlightType": "punctuation"},
            {**_text(")"), "type": "code-highlight", "highlightType": "punctuation"},
        ],
        **_ELEMENT,
    },
    {
        "type": "table",
        "children": [
            {
                "type": "tablerow",
                "children": [
                    {
                        "type": "tablecell",
                        "headerState": 1,
                        "colSpan": 1,
                        "rowSpan": 1,
                        "children": [_paragraph(_text("cell"))],
                        **_ELEMENT,
                    }
                ],
                **_ELEMENT,
            }
        ],
        **_ELEMENT,
    },
    {"type": "horizontalrule", "version": 1},
    _paragraph(
        {
            "type": "image",
            "src": "/uploads/picture.png",
            "altText": "a picture",
            "width": 0,
            "height": 0,
            "maxWidth": 500,
            "showCaption": False,
            "caption": {
                "editorState": {"root": {"type": "root", "children": [], "version": 1}}
            },
            "version": 1,
        },
        {"type": "excalidraw", "data": "[]", "width": 0, "version": 1},
    ),
    {"type": "youtube", "videoID": "dQw4w9WgXcQ", "format": "", "version": 1},
    {"type": "tweet", "id": "20", "format": "", "version": 1},
)


async def test_a_state_reads_back_as_the_document_it_was_made_from():
    state = await editor_engine.bootstrap(DOCUMENT)

    assert _without_defaults(await editor_engine.render(state)) == _without_defaults(
        DOCUMENT
    )


async def test_a_room_holds_the_state_as_the_browser_would_send_it():
    room = Doc()
    room.apply_update(await editor_engine.bootstrap(DOCUMENT))

    rendered = await editor_engine.render(bytes(room.get_update()))
    assert _without_defaults(rendered) == _without_defaults(DOCUMENT)


async def test_a_document_with_no_content_starts_with_an_empty_paragraph():
    rendered = await editor_engine.render(await editor_engine.bootstrap(None))

    assert [block["type"] for block in rendered["root"]["children"]] == ["paragraph"]
    assert rendered["root"]["children"][0]["children"] == []


async def test_legacy_nodes_come_back_as_the_browser_shows_them():
    wikilink = {
        **_text("A page nobody wrote"),
        "type": "wikilink",
        "documentId": None,
        "documentTitle": "A page nobody wrote",
    }
    hashtag = {**_text("#idea"), "type": "hashtag"}

    rendered = await editor_engine.render(
        await editor_engine.bootstrap(_document(_paragraph(wikilink, hashtag)))
    )

    (paragraph,) = rendered["root"]["children"]
    assert [node["type"] for node in paragraph["children"]] == ["text"]
    assert paragraph["children"][0]["text"] == "A page nobody wrote#idea"


async def test_content_the_editor_refuses_is_an_error():
    with pytest.raises(EditorError):
        await editor_engine.bootstrap(_document({"type": "no-such-node", "version": 1}))
