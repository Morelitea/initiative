"""A Jira issue's images, brought over as uploads (design §6.1).

An image attached to an issue becomes a blob in the bundle's ``assets/``,
restored by the ordinary backup apply under a storage key made here — so it
is quota-checked, deduplicated and registered like any other upload — and
the markdown shows it where the description or a comment embedded it.

Only raster images, and only up to :data:`MAX_IMAGE_BYTES`. Anything else
attached — a PDF, a spreadsheet — is a file document, which is a later item;
it is counted here so the plan can say what is not coming over. SVG is left
out on purpose: it is markup that can carry script, and these are files from
somebody else's site.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from app.core.messages import ImportEngineMessages
from app.services.import_engine.contract import ImportEngineError

logger = logging.getLogger(__name__)

#: The design's per-image cap.
MAX_IMAGE_BYTES = 10 * 1024 * 1024

#: The image types brought over, and the extension each is stored under.
IMAGE_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


@dataclass(frozen=True)
class Attachment:
    id: str
    filename: str
    mime_type: str
    size: int


@dataclass(frozen=True)
class StoredImage:
    """An image downloaded and given the key it will be restored under."""

    filename: str
    storage_key: str
    content_type: str
    data: bytes


@dataclass
class ImageReport:
    images: int = 0
    image_bytes: int = 0
    #: Images over the per-image cap, or past the bundle's byte budget.
    oversize: int = 0
    #: Attachments that are not images: file documents are a later item.
    other_files: int = 0
    #: Images the site would not hand over.
    unreadable: int = 0
    #: What each issue's images became, by issue key.
    by_issue: dict[str, list[StoredImage]] = field(default_factory=dict)


def issue_attachments(issue: Any) -> list[Attachment]:
    """The attachments an issue lists, skipping anything malformed."""
    fields = issue.get("fields") if isinstance(issue, dict) else None
    raw = fields.get("attachment") if isinstance(fields, dict) else None
    if not isinstance(raw, list):
        return []
    found = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        attachment_id = str(entry.get("id") or "").strip()
        filename = str(entry.get("filename") or "").strip()
        size = entry.get("size")
        if not attachment_id.isdigit() or not filename:
            continue
        found.append(
            Attachment(
                id=attachment_id,
                filename=filename,
                mime_type=str(entry.get("mimeType") or "").strip().lower(),
                size=size
                if isinstance(size, int) and not isinstance(size, bool)
                else 0,
            )
        )
    return found


def storage_key(attachment: Attachment) -> str:
    """A fresh, flat storage key — never the site's filename, which is
    somebody else's text and not a path this server should write to."""
    return f"{uuid.uuid4().hex}{IMAGE_TYPES[attachment.mime_type]}"


Downloader = Callable[[str, int], Awaitable[bytes]]


async def download_images(
    issues: list[Any],
    *,
    download: Downloader,
    budget_bytes: int,
    max_files: int,
) -> ImageReport:
    """Fetch every issue's images, within the per-image cap and a total budget.

    ``download(attachment_id, max_bytes)`` is the site call. An image the site
    will not hand over is counted and skipped — one broken attachment is not
    a reason to lose the project — but being throttled stops the fetch, as it
    does everywhere else. What would take the bundle past ``budget_bytes`` or
    ``max_files`` is skipped and counted as oversize.
    """
    report = ImageReport()
    spent = 0
    for issue in issues:
        key = str(issue.get("key") or "").strip() if isinstance(issue, dict) else ""
        for attachment in issue_attachments(issue):
            if attachment.mime_type not in IMAGE_TYPES:
                report.other_files += 1
                continue
            if (
                attachment.size > MAX_IMAGE_BYTES
                or spent + attachment.size > budget_bytes
                or report.images >= max_files
            ):
                report.oversize += 1
                continue
            try:
                data = await download(
                    attachment.id, min(MAX_IMAGE_BYTES, budget_bytes - spent)
                )
            except ImportEngineError as exc:
                if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                    raise
                if exc.code == ImportEngineMessages.IMPORT_TOO_LARGE:
                    report.oversize += 1
                else:
                    report.unreadable += 1
                continue
            spent += len(data)
            report.images += 1
            report.image_bytes += len(data)
            report.by_issue.setdefault(key, []).append(
                StoredImage(
                    filename=attachment.filename,
                    storage_key=storage_key(attachment),
                    content_type=attachment.mime_type,
                    data=data,
                )
            )
    return report


def media_urls(images: list[StoredImage], *, guild_id: int) -> dict[str, str]:
    """Filename → the URL an embedded image renders from here.

    Keyed by filename because that is what Jira puts on a media node's
    ``alt``; the node's own id is a Media Services id with no way back to the
    attachment (JRACLOUD-96384). Two attachments with one name keep the first.
    """
    urls: dict[str, str] = {}
    for image in images:
        urls.setdefault(image.filename, f"/uploads/{guild_id}/{image.storage_key}")
    return urls


def unreferenced_section(
    images: list[StoredImage], referenced: set[str], *, guild_id: int
) -> Optional[str]:
    """Markdown for the images attached but never embedded, or ``None``.

    Ends the description, under a rule, so an image somebody attached without
    placing it is still on the task rather than silently in storage.
    """
    rest = [image for image in images if image.filename not in referenced]
    if not rest:
        return None
    lines = ["---", "", "**Attachments**", ""]
    for image in rest:
        alt = image.filename.replace("]", "")
        lines.append(f"![{alt}](/uploads/{guild_id}/{image.storage_key})")
    return "\n".join(lines)
