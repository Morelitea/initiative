import { useParams } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolSettingsLayout } from "@/components/tools/settings/ToolSettingsLayout";
import {
  useDeleteGallery,
  useGallery,
  useSetGalleryGrants,
  useUpdateGallery,
} from "@/hooks/useGalleries";

export const GallerySettingsPage = () => {
  const { galleryId } = useParams({ strict: false }) as { galleryId?: string };
  const parsedId = galleryId ? Number(galleryId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const galleryQuery = useGallery(isValidId ? parsedId : null);
  const update = useUpdateGallery(parsedId);
  const setGrants = useSetGalleryGrants(parsedId);
  const remove = useDeleteGallery();

  return (
    <ToolSettingsLayout
      tool={Tool.gallery}
      entity={galleryQuery.data}
      isLoading={isValidId && galleryQuery.isLoading}
      isError={!isValidId || galleryQuery.isError}
      update={update}
      setGrants={setGrants}
      remove={remove}
    />
  );
};
