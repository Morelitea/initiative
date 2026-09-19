"""A deployment's legal documents, read through the app.

Unauthenticated: the signup form links here, and nobody is signed in yet.

The documents are served by the external portal the deployment names; this
router is the app's window onto them, so a reader on the native build — whose
origin is not an ``https://`` one — sees the same policy as a reader on the
web. A deployment that names no portal has no terms of its own, and every
route here answers 404.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel

from app.core.messages import LegalMessages
from app.services.platform import legal as legal_service

router = APIRouter()

#: Passed through from the portal, which serves a content ETag and no freshness
#: lifetime: the reader's browser keeps its copy but asks before reusing it, so
#: a corrected policy reaches them on their next look.
_CACHE_CONTROL = "public, no-cache"


class LegalDocumentRead(BaseModel):
    """One document in the index — everything but the text."""

    slug: str
    title: str
    #: What the portal calls this revision, and what an acceptance is recorded
    #: against. Null when the portal did not say.
    version: Optional[str] = None
    effective_date: Optional[date] = None
    #: Digest of the exact bytes ``/legal/{slug}`` serves.
    sha256: Optional[str] = None


class LegalIndexRead(BaseModel):
    documents: list[LegalDocumentRead]
    #: The slugs an account must accept to exist on this deployment. The SPA
    #: reads it to know which two the signup notice names.
    required: list[str]


def _require_enabled() -> None:
    if not legal_service.legal_documents_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=LegalMessages.NOT_CONFIGURED
        )


@router.get("/legal", response_model=LegalIndexRead)
async def read_legal_index() -> LegalIndexRead:
    _require_enabled()
    try:
        documents = await legal_service.get_index()
    except legal_service.LegalPortalUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=LegalMessages.PORTAL_UNAVAILABLE,
        ) from exc
    return LegalIndexRead(
        documents=[
            LegalDocumentRead(
                slug=document.slug,
                title=document.title,
                version=document.version,
                effective_date=document.effective_date,
                sha256=document.sha256,
            )
            for document in documents
        ],
        required=list(legal_service.REQUIRED_DOCUMENTS),
    )


@router.get("/legal/{slug}", response_class=Response)
async def read_legal_document(
    slug: str,
    if_none_match: Optional[str] = Header(default=None, alias="If-None-Match"),
) -> Response:
    _require_enabled()
    try:
        document = await legal_service.get_document(slug, if_none_match=if_none_match)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=LegalMessages.DOCUMENT_NOT_FOUND,
        ) from exc
    except legal_service.LegalPortalUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=LegalMessages.PORTAL_UNAVAILABLE,
        ) from exc
    headers = {"Cache-Control": _CACHE_CONTROL}
    if document.etag:
        headers["ETag"] = document.etag
    if not document.content:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(
        content=document.content, media_type=document.media_type, headers=headers
    )
