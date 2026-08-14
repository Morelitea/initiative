"""What an app calls a person, and what it must not be able to work out.

An app has to be able to name a member: to store their preferences, to say
"this is you" across two visits, and to act as them. Handing it the row id does
that and two other things nobody asked for: two apps can compare notes and
discover they are talking to the same human, and one app installed in two guilds
can link those guilds to one person. Neither is visible to the member or the
operator.

The specified answer is **OpenID Connect Core §8.1 pairwise pseudonymous
identifiers**: a subject derived per *sector*, stable within one and opaque
across them. Here the sector is the **install**, matching ``connection_ref``'s
existing precedent of being minted per (install, connection, member) and
matching the fact that apps are guild-pinned everywhere else — an app sees an
unrelated identifier for the same person in each guild it is installed in.

Two properties this shape gives, and both are load-bearing:

* **Derived, so it survives.** ``HMAC(key, sector ‖ local_id)`` regenerates the
  same value from the same inputs. Losing the stored row does not make every
  app believe it is meeting a new person.
* **One-way, so the row is not a decoder.** The stored subject cannot be turned
  back into a user id by anything that reads the table; resolution is a lookup
  of a value we minted, not an inversion.

The reverse lookup is what makes an app able to *act as* somebody: a delegation
token names its subject by this identifier, and the platform resolves it inside
the guild the token names. So a delegate knows who it is acting for without ever
learning which Initiative user that is.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.tenant.guild_app_subject import SUBJECT_LENGTH, GuildAppSubject

__all__ = [
    "SUBJECT_LENGTH",
    "derive_subject",
    "ensure_subject",
    "resolve_subject",
]

#: Its own HKDF salt, following the per-purpose pattern in
#: ``core.encryption``: rotating one boundary's key must not silently
#: re-identify everyone across another.
SALT_APP_SUBJECT = b"app-subject"


def _key() -> bytes:
    """The MAC key, derived from the deployment's own secret.

    Deliberately not the app-platform *signing* key: that one is published as a
    JWKS for apps to verify with, and a value anybody can hold must not be the
    key that makes these identifiers unguessable.
    """
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT_APP_SUBJECT,
        info=b"pairwise-subject",
    )
    return hkdf.derive(settings.SECRET_KEY.encode())


def derive_subject(*, app_install_id: int, user_id: int) -> str:
    """The pairwise subject for one member at one install.

    Pure: the same inputs give the same answer on every replica and after any
    restart, which is what lets the stored row be an index rather than the
    only copy.
    """
    # The sector and the local id are length-delimited rather than concatenated
    # raw, so (12, 345) and (123, 45) cannot derive the same subject.
    material = f"{app_install_id}:{user_id}".encode()
    digest = hmac.new(_key(), material, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")[:SUBJECT_LENGTH]


async def ensure_subject(
    session: AsyncSession, *, app_install_id: int, guild_id: int, user_id: int
) -> str:
    """This member's subject at this install, recording it for the reverse
    lookup the delegation path makes.

    Idempotent: the derivation is deterministic, so a second call writes the
    same value and races resolve to the same row.
    """
    subject = derive_subject(app_install_id=app_install_id, user_id=user_id)

    existing = (
        await session.exec(
            select(GuildAppSubject).where(GuildAppSubject.subject == subject)
        )
    ).first()
    if existing is not None:
        return subject

    session.add(
        GuildAppSubject(
            guild_id=guild_id,
            app_id=app_install_id,
            user_id=user_id,
            subject=subject,
        )
    )
    await session.flush()
    return subject


async def resolve_subject(
    session: AsyncSession, *, subject: str
) -> GuildAppSubject | None:
    """Who a subject names, within the guild the session is routed to.

    Returns the row rather than the user id so the caller can also check the
    install it belongs to — a subject minted for one app must not resolve for
    another, and the schema boundary alone does not say which app it was for.

    The session must already be routed into the guild.
    """
    if not subject or len(subject) > SUBJECT_LENGTH:
        return None
    return (
        await session.exec(
            select(GuildAppSubject).where(GuildAppSubject.subject == subject)
        )
    ).first()
