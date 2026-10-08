"""Evidence: taking a person's files in, storing them sealed, and serving them.

Every path that handles an attached file goes through here:

- :func:`prepare` holds files to their stream's policy — how many, how large,
  and what their bytes say they are — and takes a picture's location out of it
  before anything is hashed or stored.
- :func:`store` seals each file under a key of its own and writes its row, on
  the caller's session, in the caller's transaction.
- :func:`serve` streams one back, opened and checked against its hash, with
  the headers that keep a browser from treating it as anything but a download
  or a picture. Whether the reader may have the row is decided before this is
  called, by whichever session read it.
- :func:`transfer` carries a report's files into the operations case it was
  escalated to: the stored bytes are copied as they are and only the key is
  wrapped again.
- :func:`purge_due` and :func:`rewrap_guild` are the retention sweep's and the
  key rotation's halves.

Files are never written to ``uploads``: a community's uploads are readable
community-wide, and evidence is readable only through its own row.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import unicodedata
import uuid
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional, Sequence

from fastapi.responses import StreamingResponse
from sqlalchemy import and_, delete, or_, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import blob_crypto
from app.core.intake import EvidencePolicy, IntakeStream, meta
from app.core.messages import EvidenceMessages
from app.db import cohorts
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.tenant.evidence import DISPLAY_NAME_LENGTH, Evidence, EvidenceKind
from app.services import storage as storage_service

logger = logging.getLogger(__name__)

#: How evidence objects are named in their community's namespace.
_KEY_PREFIX = storage_service.EVIDENCE_KEY_PREFIX
_KEY_SUFFIX = ".iev"

#: Pictures a browser may draw inline. Anything else downloads.
_INLINE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

#: Pictures whose location is taken out before they are stored.
_EXIF_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}

#: The EXIF tag that holds where a picture was taken.
_GPS_TAG = 0x8825

_READ_CHUNK = 64 * 1024


class EvidenceRefused(Exception):
    """A file the stream does not take. ``code`` is the message to answer with."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class IncomingFile:
    """One file as a request carried it."""

    filename: Optional[str]
    data: bytes


@dataclass(frozen=True)
class PreparedEvidence:
    """A file ready to store: its bytes as they will be kept, what they are,
    and what to call them."""

    data: bytes
    content_type: str
    display_name: str
    sha256: str


# -- Taking files in ----------------------------------------------------------


def _sniff(data: bytes) -> str:
    from app.services.tenant.attachments import detect_mime_type

    detected = detect_mime_type(data) or "application/octet-stream"
    # Text of any flavour is kept as text: what it is called beyond that is a
    # guess, and nothing here renders it.
    if detected.startswith("text/"):
        return "text/plain"
    return detected


def _without_location(data: bytes, content_type: str) -> bytes:
    """``data`` with where the picture was taken removed, or as it was where
    it carries no location. Pictures of other kinds carry no EXIF to remove."""
    fmt = _EXIF_TYPES.get(content_type)
    if fmt is None:
        return data
    from PIL import Image, UnidentifiedImageError

    from app.services.tenant.galleries import MAX_IMAGE_PIXELS

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
            with Image.open(io.BytesIO(data)) as image:
                exif = image.getexif()
                if _GPS_TAG not in exif:
                    return data
                del exif[_GPS_TAG]
                params: dict[str, object] = {"exif": exif.tobytes()}
                if fmt == "JPEG":
                    # The image's own quantization: re-saved as close to the
                    # original as JPEG allows.
                    params["quality"] = "keep"
                if image.info.get("icc_profile"):
                    params["icc_profile"] = image.info["icc_profile"]
                out = io.BytesIO()
                image.save(out, format=fmt, **params)
                return out.getvalue()
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        ValueError,
    ) as exc:
        raise EvidenceRefused(EvidenceMessages.UNREADABLE) from exc


_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f/\\]+")


def clean_name(filename: Optional[str]) -> str:
    """A name to show for a file: its last path part, with control characters
    and separators taken out, and no longer than the column."""
    name = unicodedata.normalize("NFC", Path(filename or "").name)
    name = _UNSAFE_NAME.sub(" ", name).strip().strip(".")
    if not name:
        return "attachment"
    if len(name) <= DISPLAY_NAME_LENGTH:
        return name
    stem, dot, ext = name.rpartition(".")
    if dot and len(ext) <= 10:
        return f"{stem[: DISPLAY_NAME_LENGTH - len(ext) - 1]}.{ext}"
    return name[:DISPLAY_NAME_LENGTH]


def prepare(
    files: Sequence[IncomingFile], policy: EvidencePolicy
) -> list[PreparedEvidence]:
    """Hold ``files`` to ``policy`` and ready each for storing.

    Raises :class:`EvidenceRefused` for the first thing wrong; nothing is kept
    of a set that is refused.
    """
    if not files:
        return []
    if policy.max_files == 0:
        raise EvidenceRefused(EvidenceMessages.NOT_TAKEN)
    if len(files) > policy.max_files:
        raise EvidenceRefused(EvidenceMessages.TOO_MANY)
    prepared: list[PreparedEvidence] = []
    for incoming in files:
        if not incoming.data:
            raise EvidenceRefused(EvidenceMessages.EMPTY)
        if len(incoming.data) > policy.max_bytes:
            raise EvidenceRefused(EvidenceMessages.TOO_LARGE)
        content_type = _sniff(incoming.data)
        if content_type not in policy.types:
            raise EvidenceRefused(EvidenceMessages.TYPE_NOT_ALLOWED)
        data = _without_location(incoming.data, content_type)
        prepared.append(
            PreparedEvidence(
                data=data,
                content_type=content_type,
                display_name=clean_name(incoming.filename),
                sha256=hashlib.sha256(data).hexdigest(),
            )
        )
    return prepared


# -- Storing ------------------------------------------------------------------


def _key(origin_id: uuid.UUID) -> str:
    return f"{_KEY_PREFIX}{origin_id.hex}{_KEY_SUFFIX}"


def store(
    session: AsyncSession,
    *,
    guild_id: int,
    prepared: Iterable[PreparedEvidence],
    created_by: Optional[int],
    case_id: Optional[int] = None,
    report_id: Optional[int] = None,
    comment_id: Optional[int] = None,
) -> list[Evidence]:
    """Seal and store each file in ``guild_id``'s namespace, and add its row to
    ``session``, which must be routed into that community. Nothing commits
    here; :func:`discard` removes the objects of rows whose transaction did not.
    """
    storage = storage_service.get_guild_storage(guild_id)
    rows: list[Evidence] = []
    for item in prepared:
        origin_id = uuid.uuid4()
        dek = blob_crypto.new_dek()
        key = _key(origin_id)
        storage.write(
            key,
            blob_crypto.encrypt(
                item.data, dek, origin_guild_id=guild_id, origin_id=origin_id
            ),
            content_type="application/octet-stream",
        )
        row = Evidence(
            report_id=report_id,
            case_id=case_id,
            comment_id=comment_id,
            kind=EvidenceKind.attachment,
            origin_guild_id=guild_id,
            origin_id=origin_id,
            storage_key=key,
            size_bytes=len(item.data),
            content_type=item.content_type,
            display_name=item.display_name,
            sha256=item.sha256,
            wrapped_dek=blob_crypto.wrap(
                dek, holding_guild_id=guild_id, origin_id=origin_id
            ),
            kek_version=blob_crypto.KEK_VERSION,
            created_by=created_by,
        )
        session.add(row)
        rows.append(row)
    return rows


def discard(guild_id: int, rows: Iterable[Evidence]) -> None:
    """Remove the stored objects of rows that were never committed."""
    storage = storage_service.get_guild_storage(guild_id)
    for row in rows:
        try:
            storage.delete(row.storage_key)
        except Exception:  # pragma: no cover - best effort, logged
            logger.exception("evidence: could not remove %s", row.storage_key)


# -- Listing ------------------------------------------------------------------


async def listed(
    session: AsyncSession,
    *,
    report_ids: Sequence[int] = (),
    case_ids: Sequence[int] = (),
) -> dict[tuple[str, int], list[Evidence]]:
    """The files attached to these reports and cases, read on ``session`` and
    keyed ``("report", id)`` or ``("case", id)``, oldest first. One statement,
    whatever the page holds."""
    if not report_ids and not case_ids:
        return {}
    conditions = []
    if report_ids:
        conditions.append(Evidence.report_id.in_(tuple(report_ids)))  # type: ignore[union-attr]
    if case_ids:
        conditions.append(Evidence.case_id.in_(tuple(case_ids)))  # type: ignore[union-attr]
    rows = (
        await session.exec(
            select(Evidence)
            .where(or_(*conditions))
            .order_by(Evidence.created_at, Evidence.id)
        )
    ).all()
    found: dict[tuple[str, int], list[Evidence]] = {}
    for row in rows:
        key = ("report", row.report_id) if row.report_id else ("case", row.case_id)
        found.setdefault(key, []).append(row)  # type: ignore[arg-type]
    return found


# -- Serving ------------------------------------------------------------------


@dataclass(frozen=True)
class SealedObject:
    """What opening one stored object takes, read from its row."""

    storage_key: str
    origin_guild_id: int
    origin_id: uuid.UUID
    wrapped_dek: bytes
    kek_version: int
    sha256: str
    content_type: str
    display_name: str
    size_bytes: int


async def sealed(session: AsyncSession, evidence_id: int) -> Optional[SealedObject]:
    """The stored half of row ``evidence_id``, read on ``session`` — a system
    session routed into the community holding it, once the reader's own
    session has shown the row is theirs to read."""
    row = (
        await session.exec(
            select(
                Evidence.storage_key,
                Evidence.origin_guild_id,
                Evidence.origin_id,
                Evidence.wrapped_dek,
                Evidence.kek_version,
                Evidence.sha256,
                Evidence.content_type,
                Evidence.display_name,
                Evidence.size_bytes,
            ).where(Evidence.id == evidence_id)
        )
    ).first()
    return SealedObject(*row) if row is not None else None


def _stored_bytes(guild_id: int, key: str) -> Iterator[bytes]:
    blob = storage_service.get_guild_storage(guild_id).open_readable(key)
    if blob is None:
        raise EvidenceRefused(EvidenceMessages.NOT_FOUND)
    if blob.path is not None:
        with blob.path.open("rb") as handle:
            while piece := handle.read(_READ_CHUNK):
                yield piece
        return
    yield from blob.stream or ()


def plaintext(guild_id: int, obj: SealedObject) -> Iterator[bytes]:
    """The object's bytes as they were stored, a chunk at a time, checked
    against the row's hash once the last one is out."""
    dek = blob_crypto.unwrap(
        obj.wrapped_dek,
        holding_guild_id=guild_id,
        origin_id=obj.origin_id,
        version=obj.kek_version,
    )
    digest = hashlib.sha256()
    for chunk in blob_crypto.decrypt_stream(
        _stored_bytes(guild_id, obj.storage_key),
        dek,
        origin_guild_id=obj.origin_guild_id,
        origin_id=obj.origin_id,
    ):
        digest.update(chunk)
        yield chunk
    if digest.hexdigest() != obj.sha256:
        raise blob_crypto.BlobCryptoError("the object is not the one its row names")


def serve(guild_id: int, obj: SealedObject) -> StreamingResponse:
    """A response streaming one object, opened. Pictures are shown; anything
    else is downloaded. Never cached, never sniffed, never run."""
    from app.services.storage import content_disposition_attachment

    inline = obj.content_type in _INLINE_TYPES
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'",
        "Content-Length": str(obj.size_bytes),
        "Content-Disposition": (
            "inline" if inline else content_disposition_attachment(obj.display_name)
        ),
    }
    return StreamingResponse(
        plaintext(guild_id, obj),
        media_type=obj.content_type if inline else "application/octet-stream",
        headers=headers,
    )


# -- Crossing communities -----------------------------------------------------


async def transfer(
    *,
    source_guild_id: int,
    rows: Sequence[Evidence],
    destination: AsyncSession,
    destination_guild_id: int,
    case_id: int,
) -> list[Evidence]:
    """Carry ``rows`` — read in ``source_guild_id`` — into the operations case
    ``case_id``, on ``destination``, a system session routed into
    ``destination_guild_id``.

    Each object is copied as it is stored; it is never opened. Its key is
    unwrapped with the source community's key and wrapped with the
    destination's, and the new row keeps the object's origin and hash, which is
    what its bytes are bound to. Nothing commits here.
    """
    already = set(
        (
            await destination.exec(
                select(Evidence.origin_id).where(Evidence.case_id == case_id)
            )
        ).all()
    )
    same_community = int(source_guild_id) == int(destination_guild_id)
    carried: list[Evidence] = []
    for row in rows:
        if row.origin_id in already:
            # Carried by an earlier escalation of the same report.
            continue
        if not same_community and not storage_service.copy_between_guilds(
            source_guild_id, destination_guild_id, row.storage_key
        ):
            logger.warning(
                "evidence: %s is gone from community %s; not carried",
                row.storage_key,
                source_guild_id,
            )
            continue
        dek = blob_crypto.unwrap(
            row.wrapped_dek,
            holding_guild_id=source_guild_id,
            origin_id=row.origin_id,
            version=row.kek_version,
        )
        copy = Evidence(
            case_id=case_id,
            kind=row.kind,
            origin_guild_id=row.origin_guild_id,
            origin_id=row.origin_id,
            storage_key=row.storage_key,
            size_bytes=row.size_bytes,
            content_type=row.content_type,
            display_name=row.display_name,
            sha256=row.sha256,
            wrapped_dek=blob_crypto.wrap(
                dek, holding_guild_id=destination_guild_id, origin_id=row.origin_id
            ),
            kek_version=blob_crypto.KEK_VERSION,
            created_by=row.created_by,
        )
        destination.add(copy)
        carried.append(copy)
    return carried


async def carry_report(
    session: AsyncSession,
    *,
    source_guild_id: int,
    report_id: int,
    case_id: int,
) -> int:
    """Carry what was attached to community report ``report_id`` — read on
    ``session``, routed into ``source_guild_id`` — into operations case
    ``case_id``. Returns how many files were carried.

    Its own transaction in the operations community, committed before the
    report closes: a report closed as escalated has handed its files over.
    """
    from app.services.platform.intake import configured_operations_guild_id

    rows = (
        await session.exec(select(Evidence).where(Evidence.report_id == report_id))
    ).all()
    if not rows:
        return 0
    operations = await configured_operations_guild_id()
    if operations is None:
        return 0
    async with cohorts.system_session(operations) as destination:
        await set_rls_context(destination, SystemGuild(operations))
        carried = await transfer(
            source_guild_id=source_guild_id,
            rows=rows,
            destination=destination,
            destination_guild_id=operations,
            case_id=case_id,
        )
        try:
            await destination.commit()
        except BaseException:
            if int(operations) != int(source_guild_id):
                discard(operations, carried)
            raise
    return len(carried)


# -- Retention ----------------------------------------------------------------


async def purge_due(session: AsyncSession, guild_id: int) -> int:
    """One community's retention: date the evidence of what has closed, undate
    what has reopened, and delete what is past its date — the row, then the
    object. Returns how many went.

    A case closes when its task is done or in the trash, and its evidence is
    kept for its stream's ``retention_days`` from then. A report closes when it
    is settled, and its evidence is kept for the moderation stream's.
    """
    from app.models.tenant.intake import IntakeCase
    from app.models.tenant.moderation import ModerationReport
    from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory

    now = datetime.now(timezone.utc)
    closed_case = (
        select(IntakeCase.id)
        .join(Task, Task.id == IntakeCase.task_id)
        .join(TaskStatus, TaskStatus.id == Task.task_status_id)
        .where(
            or_(
                Task.deleted_at.is_not(None),  # type: ignore[union-attr]
                TaskStatus.category == TaskStatusCategory.done,
            )
        )
    )
    for stream in IntakeStream:
        keep = timedelta(days=meta(stream).retention_days)
        of_stream = closed_case.where(IntakeCase.stream == stream.value)
        await session.exec(
            update(Evidence)
            .where(Evidence.case_id.in_(of_stream))  # type: ignore[union-attr]
            .where(Evidence.purge_after.is_(None))  # type: ignore[union-attr]
            .values(purge_after=now + keep)
        )
    await session.exec(
        update(Evidence)
        .where(Evidence.case_id.is_not(None))  # type: ignore[union-attr]
        .where(Evidence.case_id.not_in(closed_case))  # type: ignore[union-attr]
        .where(Evidence.purge_after.is_not(None))  # type: ignore[union-attr]
        .values(purge_after=None)
    )
    report_keep = timedelta(days=meta(IntakeStream.moderation).retention_days)
    await session.exec(
        update(Evidence)
        .where(Evidence.report_id.is_not(None))  # type: ignore[union-attr]
        .where(Evidence.purge_after.is_(None))  # type: ignore[union-attr]
        .where(
            Evidence.report_id.in_(  # type: ignore[union-attr]
                select(ModerationReport.id).where(
                    ModerationReport.decided_at.is_not(None)  # type: ignore[union-attr]
                )
            )
        )
        .values(purge_after=now + report_keep)
    )
    gone = (
        await session.exec(
            delete(Evidence)
            .where(
                and_(
                    Evidence.purge_after.is_not(None),  # type: ignore[union-attr]
                    Evidence.purge_after < now,  # type: ignore[operator]
                )
            )
            .returning(Evidence.storage_key)
        )
    ).all()
    await session.commit()
    if gone:
        storage = storage_service.get_guild_storage(guild_id)
        for (key,) in gone:
            # Another row may still name the object: a report's evidence and a
            # case it was carried into in the same community share none, but
            # this keeps that true rather than assuming it.
            still = (
                await session.exec(
                    select(Evidence.id).where(Evidence.storage_key == key).limit(1)
                )
            ).first()
            if still is None:
                storage.delete(key)
        logger.info("evidence: purged %s from community %s", len(gone), guild_id)
    return len(gone)


# -- Key rotation -------------------------------------------------------------


async def rewrap_guild(
    session: AsyncSession,
    guild_id: int,
    *,
    old_secret_key: str,
    new_secret_key: str,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """Wrap every evidence key in ``guild_id`` under ``new_secret_key``.
    Objects are not touched. Returns ``(rotated, skipped, failed)``: a key
    that already unwraps under the new secret is skipped, one that unwraps
    under neither is counted and left."""
    rows = (
        await session.exec(
            select(Evidence.id, Evidence.origin_id, Evidence.wrapped_dek)
        )
    ).all()
    rotated = skipped = failed = 0
    for evidence_id, origin_id, wrapped in rows:
        try:
            blob_crypto.unwrap(
                wrapped,
                holding_guild_id=guild_id,
                origin_id=origin_id,
                secret_key=new_secret_key,
            )
            skipped += 1
            continue
        except blob_crypto.BlobCryptoError:
            pass
        try:
            new = blob_crypto.rewrap(
                wrapped,
                holding_guild_id=guild_id,
                origin_id=origin_id,
                old_secret_key=old_secret_key,
                new_secret_key=new_secret_key,
            )
        except blob_crypto.BlobCryptoError:
            failed += 1
            continue
        rotated += 1
        if not dry_run:
            await session.exec(
                update(Evidence)
                .where(Evidence.id == evidence_id)
                .values(wrapped_dek=new, kek_version=blob_crypto.KEK_VERSION)
            )
    return rotated, skipped, failed
