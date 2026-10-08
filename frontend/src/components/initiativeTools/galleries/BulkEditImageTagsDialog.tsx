import { type GalleryImageRead, TagTarget } from "@/api/generated/initiativeAPI.schemas";
import { BulkEditTagsDialog } from "@/components/shared/BulkEditTagsDialog";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { invalidateImages } from "@/hooks/useGalleries";
import type { DialogWithSuccessProps } from "@/types/dialog";

interface BulkEditImageTagsDialogProps extends DialogWithSuccessProps {
  galleryId: number;
  images: GalleryImageRead[];
}

/** Tagging a selection of pictures — the shared bulk-tag dialog, pointed at
 *  the gallery-image target and this gallery's caches. */
export function BulkEditImageTagsDialog({
  galleryId,
  images,
  ...dialogProps
}: BulkEditImageTagsDialogProps) {
  const communityId = useActiveCommunityId();

  return (
    <BulkEditTagsDialog
      {...dialogProps}
      items={images}
      targetType={TagTarget.gallery_image}
      communityId={communityId}
      onInvalidate={() => void invalidateImages(galleryId)}
    />
  );
}
