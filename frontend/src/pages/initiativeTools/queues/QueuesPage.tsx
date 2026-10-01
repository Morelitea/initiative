import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolIndexPage } from "@/components/tools/ToolIndexPage";

type QueuesViewProps = {
  /** The initiative this list belongs to. Required: queues are only ever
   *  browsed inside one, and the URL says which. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/** An initiative's queues, as cards. */
export const QueuesView = (props: QueuesViewProps) => (
  <ToolIndexPage tool={Tool.queue} {...props} />
);
