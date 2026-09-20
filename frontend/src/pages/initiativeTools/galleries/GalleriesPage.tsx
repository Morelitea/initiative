import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolIndexPage } from "@/components/tools/ToolIndexPage";

type GalleriesViewProps = {
  /** The initiative this list belongs to. Required: galleries are only ever
   *  browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/**
 * An initiative's galleries, as cards led by their covers.
 *
 * The list is the shelf; each gallery is its own wall. Search here reads the
 * index (name and description) — the filter box that finds a picture by its
 * caption is on the gallery's own page, where the pictures are.
 */
export const GalleriesView = (props: GalleriesViewProps) => (
  <ToolIndexPage tool={Tool.gallery} {...props} />
);
