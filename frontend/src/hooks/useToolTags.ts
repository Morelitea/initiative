import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { setToolTagsApiV1GGuildIdToolsToolToolIdTagsPut } from "@/api/generated/tools/tools";
import {
  invalidateAdvancedTool,
  invalidateAllAdvancedTools,
  invalidateAllCalendarEvents,
  invalidateAllCounterGroups,
  invalidateAllDocuments,
  invalidateAllProjects,
  invalidateAllQueues,
  invalidateCalendarEvent,
  invalidateCounterGroup,
  invalidateQueue,
} from "@/api/query-keys";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

/**
 * The one set-tags mutation for every tool — PUTs the FULL tag id list (the
 * picker owns the complete selection, so there is no read-modify) to the
 * generic `/tools/{tool}/{toolId}/tags` route, then invalidates that tool's
 * list + detail queries so every consumer reflects the change.
 *
 * The invalidator map is `Record<Tool, …>`, so a new Tool member fails to
 * compile until it declares its invalidation here. Tasks and queue items are
 * sub-resources, not tools — their set-tags hooks live with their own
 * feature hooks (`useSetTaskTags`, `useSetQueueItemTags`).
 */

const TOOL_TAG_INVALIDATORS: Record<Tool, (id: number) => void> = {
  [Tool.project]: () => void invalidateAllProjects(),
  [Tool.document]: () => void invalidateAllDocuments(),
  [Tool.queue]: (id) => {
    void invalidateQueue(id);
    void invalidateAllQueues();
  },
  [Tool.counter_group]: (id) => {
    void invalidateCounterGroup(id);
    void invalidateAllCounterGroups();
  },
  [Tool.calendar_event]: (id) => {
    void invalidateCalendarEvent(id);
    void invalidateAllCalendarEvents();
  },
  [Tool.advanced_tool]: (id) => {
    void invalidateAdvancedTool(id);
    void invalidateAllAdvancedTools();
  },
};

export const useSetToolTags = (
  tool: Tool,
  options?: MutationOpts<TagSummary[], { id: number; tagIds: number[] }>
) =>
  useGuildMutation<TagSummary[], { id: number; tagIds: number[] }>(
    {
      mutationFn: (guildId, { id, tagIds }) =>
        setToolTagsApiV1GGuildIdToolsToolToolIdTagsPut(guildId, tool, id, {
          tag_ids: tagIds,
        }),
      invalidate: (_data, vars) => TOOL_TAG_INVALIDATORS[tool](vars.id),
      errorKey: "tags:toolTagsError",
    },
    options
  );
