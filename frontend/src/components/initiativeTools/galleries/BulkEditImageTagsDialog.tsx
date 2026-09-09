import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { GalleryImageRead } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { BulkEditTagsDialog as GenericBulkEditTagsDialog } from "@/components/shared/BulkEditTagsDialog";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
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
  const { t } = useTranslation(["galleries", "common"]);
  const guildId = useActiveGuildId();

  const labels = useMemo(
    () => ({
      title: t("bulkTags.title"),
      descriptionAdd: t("bulkTags.descriptionAdd", { count: images.length }),
      descriptionRemove: t("bulkTags.descriptionRemove", { count: images.length }),
      tabAdd: t("bulkTags.tabAdd"),
      tabRemove: t("bulkTags.tabRemove"),
      addPlaceholder: t("bulkTags.addPlaceholder"),
      removePlaceholder: t("bulkTags.removePlaceholder"),
      noTags: t("bulkTags.noTags"),
      tagsAdded: t("bulkTags.tagsAdded", { count: images.length }),
      tagsRemoved: t("bulkTags.tagsRemoved", { count: images.length }),
      applying: t("bulkTags.applying"),
      apply: t("bulkTags.apply"),
      cancel: t("common:cancel"),
      updateError: t("bulkTags.updateError"),
    }),
    [t, images.length]
  );

  return (
    <GenericBulkEditTagsDialog
      {...dialogProps}
      items={images}
      targetType="gallery_image"
      guildId={guildId}
      onInvalidate={() =>
        void invalidate(q.galleryImages(galleryId), q.gallery(galleryId), q.allGalleries())
      }
      labels={labels}
    />
  );
}
