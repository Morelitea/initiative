import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolIndexPage } from "@/components/tools/ToolIndexPage";

type DocumentsViewProps = {
  /** The initiative this list belongs to. Required: documents are only ever
   *  browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/** An initiative's documents: cards, a table, or browsed by tag. */
export const DocumentsView = (props: DocumentsViewProps) => (
  <ToolIndexPage tool={Tool.document} {...props} />
);
