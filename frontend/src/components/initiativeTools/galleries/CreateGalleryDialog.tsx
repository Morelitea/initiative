import type { GalleryRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  type CreateToolConfig,
  CreateToolDialog,
  type CreateToolDialogProps,
} from "@/components/initiativeTools/shared/CreateToolDialog";
import { useCreateGallery } from "@/hooks/useGalleries";

const config: CreateToolConfig<GalleryRead> = {
  tool: Tool.gallery,
  namespace: "galleries",
  titleKey: "createGallery",
  descriptionKey: "createGalleryDescription",
  idPrefix: "create-gallery",
  useCreate: useCreateGallery,
};

/**
 * Naming an empty gallery. The pictures come afterwards, on its own page,
 * where they can be dropped in forty at a time — which is why this is the
 * shared name-and-describe dialog and not a picker.
 */
export const CreateGalleryDialog = (props: Omit<CreateToolDialogProps<GalleryRead>, "config">) => (
  <CreateToolDialog {...props} config={config} />
);
