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


def picture(*, located: bool = False, fmt: str = "JPEG") -> bytes:
    image = Image.new("RGB", (8, 8), "red")
    exif = Image.Exif()
    exif[0x010F] = "Camera"
    if located:
        gps = exif.get_ifd(0x8825)
        gps[1] = "N"
        gps[2] = (51.0, 30.0, 0.0)
    out = io.BytesIO()
    image.save(out, fmt, exif=exif.tobytes())
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
