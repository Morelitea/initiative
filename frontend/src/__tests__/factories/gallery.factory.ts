import type { GalleryImageRead, GalleryRead } from "@/api/generated/initiativeAPI.schemas";

let counter = 0;
let imageCounter = 0;

export function resetCounter(): void {
  counter = 0;
  imageCounter = 0;
}

export function buildGallery(overrides: Partial<GalleryRead> = {}): GalleryRead {
  counter++;
  return {
    id: counter,
    name: `Gallery ${counter}`,
    description: null,
    initiative_id: 1,
    guild_id: 1,
    created_by: 1,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    image_count: 0,
    cover_image_id: null,
    cover: null,
    preview: [],
    archived_at: null,
    can_unarchive: false,
    my_permission_level: "owner",
    comments_enabled: true,
    comment_count: 0,
    tags: [],
    grants: [],
    ...overrides,
  };
}

/**
 * One picture in a gallery. Sized and thumbnailed by default — the shape a
 * real upload has — so the layouts under test reserve space the way they
 * would for a real one.
 */
export function buildGalleryImage(overrides: Partial<GalleryImageRead> = {}): GalleryImageRead {
  imageCounter++;
  return {
    id: imageCounter,
    gallery_id: 1,
    guild_id: 1,
    title: `Picture ${imageCounter}`,
    caption: null,
    file_url: `/uploads/1/picture-${imageCounter}.png`,
    thumbnail_url: `/uploads/1/picture-${imageCounter}-thumb.webp`,
    file_content_type: "image/png",
    file_size: 12_345,
    original_filename: `picture-${imageCounter}.png`,
    width: 1200,
    height: 800,
    created_by: 1,
    uploader: null,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    version_count: 1,
    tags: [],
    ...overrides,
  };
}
