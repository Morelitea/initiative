import type { TagSummary, Tool } from "@/api/generated/initiativeAPI.schemas";
import { setToolTagsApiV1GGuildIdToolsToolToolIdTagsPut } from "@/api/generated/tools/tools";
import { invalidateTool } from "@/api/query-keys";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

/**
 * The one set-tags mutation for every tool — PUTs the FULL tag id list (the
 * picker owns the complete selection, so there is no read-modify) to the
 * generic `/tools/{tool}/{toolId}/tags` route, then invalidates that tool's
 * list + detail queries so every consumer reflects the change.
 *
 * Tasks and queue items are sub-resources, not tools — their set-tags hooks
 * live with their own feature hooks (`useSetTaskTags`, `useSetQueueItemTags`).
 */
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
      invalidate: (_data, vars) => invalidateTool(tool, vars.id),
      errorKey: "tags:toolTagsError",
    },
    options
  );
