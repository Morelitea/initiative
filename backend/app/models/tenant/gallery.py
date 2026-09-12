from datetime import datetime, timezone
from typing import ClassVar, List, Optional, TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlmodel import Field, Relationship

from app.models.tenant._mixins import (
    ArchiveMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    SoftDeleteMixin,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.initiative import Initiative
    from app.models.tenant.resource_grant import ResourceGrant
    from app.models.platform.user_profile_view import MemberProfile


class Gallery(
    CommentsToggleMixin, CreatedByMixin, ArchiveMixin, SoftDeleteMixin, table=True
):
    """A collection of pictures in an initiative.

    A gallery is a whole tool entity — its own sharing, its own comment thread,
    tags, the trash can, a URL — and its pictures are child rows the way a
    project's tasks are. That split is what the tool is for: a hundred canvases
    are one thing to share and one thing to open, and then browsed as many.

    ``name`` is the shared display column every tool spells the same;
    ``description`` is what a gallery is *of*, shown on its card and indexed
    for search.

    ``cover_image_id`` is the picture that stands for the gallery in a list.
    Nullable, because most galleries never choose one: a list falls back to the
    newest picture, which is what a gallery someone is still filling looks like
    from outside. The foreign key is declared ``use_alter`` because the two
    tables point at each other — a gallery names its cover, a picture names its
    gallery — and one of the constraints has to be added after both exist.
    ``SET NULL`` so removing the chosen picture leaves the gallery with no cover
    rather than no gallery.
    """

    __tablename__ = "galleries"
    # A tool row is written before anything has been shared, so it is read
    # back by no RETURNING clause: the id comes from the sequence first and
    # the INSERT stands alone. See app/db/initiative_rls.py.
    __table_args__ = {"implicit_returning": False}

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(nullable=False, max_length=255)
    description: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    cover_image_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey(
                "gallery_images.id",
                ondelete="SET NULL",
                use_alter=True,
                name="galleries_cover_image_id_fkey",
            ),
            nullable=True,
        ),
    )
    created_by: int = Field(foreign_key="users.id", nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    initiative: Optional["Initiative"] = Relationship()
    grants: List["ResourceGrant"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(ResourceGrant.resource_id) == Gallery.id, "
                "ResourceGrant.resource_type == 'gallery')"
            ),
            "viewonly": True,
        }
    )
    # The pictures. Ordered newest first here because that is the one order
    # every surface wants — a gallery is a record of what arrived, and the
    # latest arrival is what somebody opening it came to see.
    images: List["GalleryImage"] = Relationship(
        back_populates="gallery",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "desc(GalleryImage.created_at)",
            "foreign_keys": "GalleryImage.gallery_id",
        },
    )
    cover_image: Optional["GalleryImage"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "Gallery.cover_image_id == GalleryImage.id",
            "foreign_keys": "Gallery.cover_image_id",
            "viewonly": True,
        }
    )


class GalleryImage(CreatedByMixin, SoftDeleteMixin, table=True):
    """One picture in a gallery.

    The file columns mirror the picture's *current* version — the highest
    ``version_number`` in :class:`GalleryImageVersion` — the same arrangement a
    file document keeps, so the gallery can be drawn from this table alone and
    the history is there when somebody asks for it.

    ``width`` and ``height`` are read from the file's header at upload, and
    they are what lets a masonry layout reserve the right space for a picture
    before its bytes arrive. ``thumbnail_url`` is a smaller rendition made at
    upload for the grid; ``NULL`` where none could be made, and the grid then
    shows the picture itself.

    ``title`` is optional — most pictures are named by what they show — and
    surfaces fall back to the original filename, which is at least what the
    person who uploaded it called it.
    """

    __tablename__ = "gallery_images"
    # What labels a picture in a bare list of mixed things (the trash can).
    # Often empty, and the trash then shows the row with no name — which is
    # still the row, and still restorable.
    _display_field: ClassVar[str] = "title"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", nullable=False, index=True)
    gallery_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("galleries.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    title: Optional[str] = Field(
        default=None, sa_column=Column(String(length=255), nullable=True)
    )
    caption: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    file_url: str = Field(sa_column=Column(String(length=512), nullable=False))
    thumbnail_url: Optional[str] = Field(
        default=None, sa_column=Column(String(length=512), nullable=True)
    )
    file_content_type: Optional[str] = Field(
        default=None, sa_column=Column(String(length=128), nullable=True)
    )
    file_size: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    original_filename: Optional[str] = Field(
        default=None, sa_column=Column(String(length=255), nullable=True)
    )
    width: Optional[int] = Field(default=None, nullable=True)
    height: Optional[int] = Field(default=None, nullable=True)
    created_by: int = Field(foreign_key="users.id", nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    gallery: Optional[Gallery] = Relationship(
        back_populates="images",
        sa_relationship_kwargs={"foreign_keys": "GalleryImage.gallery_id"},
    )
    uploader: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(GalleryImage.created_by) == MemberProfile.id",
            "viewonly": True,
        }
    )
    versions: List["GalleryImageVersion"] = Relationship(
        back_populates="image",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "GalleryImageVersion.version_number",
        },
    )


class GalleryImageVersion(CreatedByMixin, table=True):
    """One uploaded rendition of a picture.

    Every picture has at least one row here, and the ``gallery_images`` row
    mirrors the newest. The same shape a file document's versions take, for the
    same reason: a design round replaces a canvas rather than adding one, and
    the earlier rounds are the story of how it got there.
    """

    __tablename__ = "gallery_image_versions"
    __table_args__ = (
        UniqueConstraint(
            "gallery_image_id", "version_number", name="uq_giv_image_version"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    gallery_image_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("gallery_images.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    guild_id: int = Field(foreign_key="guilds.id", nullable=False)
    version_number: int = Field(nullable=False)
    file_url: str = Field(sa_column=Column(String(length=512), nullable=False))
    thumbnail_url: Optional[str] = Field(
        default=None, sa_column=Column(String(length=512), nullable=True)
    )
    file_content_type: Optional[str] = Field(
        default=None, sa_column=Column(String(length=128), nullable=True)
    )
    file_size: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    original_filename: Optional[str] = Field(
        default=None, sa_column=Column(String(length=255), nullable=True)
    )
    width: Optional[int] = Field(default=None, nullable=True)
    height: Optional[int] = Field(default=None, nullable=True)
    created_by: int = Field(foreign_key="users.id", nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    image: Optional[GalleryImage] = Relationship(back_populates="versions")
