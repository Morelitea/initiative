"""Taking a person's files in: held to their stream, and stripped of where a
picture was taken before anything is kept."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core.intake import IMAGE_TYPES, EvidencePolicy, IntakeStream, meta
from app.core.messages import EvidenceMessages
from app.services.platform import evidence
from app.services.platform.evidence import EvidenceRefused, IncomingFile

POLICY = meta(IntakeStream.support).evidence


def _exif(located: bool) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Camera"
    exif[0x0110] = "A model name long enough to be stored apart from its entry"
    if located:
        gps = exif.get_ifd(0x8825)
        gps[1] = "N"
        gps[2] = (51.0, 30.0, 0.0)
    return exif.tobytes()


def picture(*, located: bool = False, fmt: str = "JPEG") -> bytes:
    image = Image.new("RGB", (8, 8), "red")
    out = io.BytesIO()
    image.save(out, fmt, exif=_exif(located))
    return out.getvalue()


def animation(*, located: bool, fmt: str) -> bytes:
    frames = [Image.new("RGB", (8, 8), colour) for colour in ("red", "green", "blue")]
    out = io.BytesIO()
    frames[0].save(
        out,
        fmt,
        save_all=True,
        append_images=frames[1:],
        duration=[100, 200, 300],
        loop=0,
        exif=_exif(located),
        **({"lossless": True} if fmt == "WEBP" else {}),
    )
    return out.getvalue()


def test_a_picture_keeps_nothing_of_where_it_was_taken():
    (kept,) = evidence.prepare(
        [IncomingFile("holiday.jpg", picture(located=True))], POLICY
    )
    exif = Image.open(io.BytesIO(kept.data)).getexif()
    assert 0x8825 not in exif
    # Only the location goes: the rest of what the picture says stays.
    assert exif.get(0x010F) == "Camera"
    assert kept.content_type == "image/jpeg"


@pytest.mark.parametrize(
    ("fmt", "content_type"),
    [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")],
)
def test_only_the_location_changes(fmt, content_type):
    sent = picture(located=True, fmt=fmt)
    (kept,) = evidence.prepare([IncomingFile("a", sent)], POLICY)
    assert kept.content_type == content_type
    # Not re-encoded: the same length, and the same pixels.
    assert len(kept.data) == len(sent)
    with (
        Image.open(io.BytesIO(kept.data)) as after,
        Image.open(io.BytesIO(sent)) as before,
    ):
        assert after.tobytes() == before.tobytes()
        exif = after.getexif()
        assert 0x8825 not in exif
        assert exif.get(0x010F) == "Camera"
        assert exif.get(0x0110).startswith("A model name")
    # The degrees themselves are gone from the bytes, not just unlinked.
    degrees = [
        d
        for d in (
            b"\x00\x00\x00\x33\x00\x00\x00\x01",
            b"\x33\x00\x00\x00\x01\x00\x00\x00",
        )
        if d in sent
    ]
    assert degrees
    assert all(d not in kept.data for d in degrees)


def _frames(data: bytes) -> list[tuple[bytes, object]]:
    with Image.open(io.BytesIO(data)) as image:
        seen = []
        for frame in range(image.n_frames):
            image.seek(frame)
            seen.append(
                (
                    image.convert("RGB").tobytes(),
                    image.info.get("duration", image.info.get("timestamp")),
                )
            )
        return seen


@pytest.mark.parametrize("fmt", ["PNG", "WEBP"])
def test_an_animation_keeps_every_frame_and_its_timing(fmt):
    sent = animation(located=True, fmt=fmt)
    (kept,) = evidence.prepare([IncomingFile("a", sent)], POLICY)
    with Image.open(io.BytesIO(kept.data)) as after:
        assert 0x8825 not in after.getexif()
    frames = _frames(kept.data)
    assert len(frames) == 3
    assert frames == _frames(sent)


def test_a_picture_whose_location_cannot_be_read_is_refused():
    sent = bytearray(picture(located=True))
    # Point the location directory past the end of its block.
    at = sent.index(b"Exif\x00\x00") + 6
    order = "<" if sent[at : at + 2] == b"II" else ">"
    import struct

    ifd0 = at + struct.unpack_from(order + "I", sent, at + 4)[0]
    for i in range(struct.unpack_from(order + "H", sent, ifd0)[0]):
        entry = ifd0 + 2 + 12 * i
        if struct.unpack_from(order + "H", sent, entry)[0] == 0x8825:
            struct.pack_into(order + "I", sent, entry + 8, 0xFFFFFF)
    with pytest.raises(EvidenceRefused) as refused:
        evidence.prepare([IncomingFile("a.jpg", bytes(sent))], POLICY)
    assert refused.value.code == EvidenceMessages.UNREADABLE


def test_a_picture_with_no_location_is_kept_as_it_came():
    data = picture()
    (kept,) = evidence.prepare([IncomingFile("a.jpg", data)], POLICY)
    assert kept.data == data


def test_the_hash_is_of_what_is_kept():
    import hashlib

    (kept,) = evidence.prepare([IncomingFile("a.jpg", picture(located=True))], POLICY)
    assert kept.sha256 == hashlib.sha256(kept.data).hexdigest()


def test_a_file_is_what_its_bytes_say_not_what_it_is_called():
    with pytest.raises(EvidenceRefused) as refused:
        evidence.prepare(
            [IncomingFile("photo.jpg", b"#!/bin/sh\necho hi\n" + b"\x00" * 64)],
            EvidencePolicy(5, 1024, IMAGE_TYPES),
        )
    assert refused.value.code == EvidenceMessages.TYPE_NOT_ALLOWED


@pytest.mark.parametrize(
    ("files", "code"),
    [
        ([IncomingFile("a.jpg", b"")], EvidenceMessages.EMPTY),
        (
            [IncomingFile(f"{n}.jpg", picture()) for n in range(6)],
            EvidenceMessages.TOO_MANY,
        ),
    ],
)
def test_what_a_stream_will_not_take_is_refused(files, code):
    with pytest.raises(EvidenceRefused) as refused:
        evidence.prepare(files, POLICY)
    assert refused.value.code == code


def test_a_file_larger_than_the_stream_takes_is_refused():
    with pytest.raises(EvidenceRefused) as refused:
        evidence.prepare(
            [IncomingFile("a.jpg", picture())], EvidencePolicy(1, 10, IMAGE_TYPES)
        )
    assert refused.value.code == EvidenceMessages.TOO_LARGE


def test_a_stream_that_takes_nothing_says_so():
    with pytest.raises(EvidenceRefused) as refused:
        evidence.prepare(
            [IncomingFile("a.jpg", picture())], EvidencePolicy(0, 0, frozenset())
        )
    assert refused.value.code == EvidenceMessages.NOT_TAKEN


@pytest.mark.parametrize(
    ("given", "shown"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\scan.pdf", "C: Users me scan.pdf"),
        ("bad\x00name\n.txt", "bad name .txt"),
        ("", "attachment"),
        (None, "attachment"),
        ("x" * 300 + ".png", "x" * 196 + ".png"),
    ],
)
def test_a_name_is_shown_cleaned(given, shown):
    assert evidence.clean_name(given) == shown
