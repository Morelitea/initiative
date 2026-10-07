import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolIndexPage } from "@/components/tools/ToolIndexPage";

type FilesViewProps = {
  /** The initiative this list belongs to. Required: files are only ever
   *  browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/** An initiative's files: cards, a table, or browsed by tag. */
export const FilesView = (props: FilesViewProps) => <ToolIndexPage tool={Tool.file} {...props} />;
