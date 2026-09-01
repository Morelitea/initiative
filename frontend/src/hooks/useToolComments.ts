import type { Tool, ToolCommentSettings } from "@/api/generated/initiativeAPI.schemas";
import { setToolCommentSettingsApiV1GGuildIdToolsToolToolIdCommentsPut } from "@/api/generated/tools/tools";
import { invalidateAllComments, invalidateTool } from "@/api/query-keys";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

/**
 * The one comment-switch mutation for every tool — PUTs the new state to the
 * generic `/tools/{tool}/{toolId}/comments` route, then invalidates that tool's
 * list + detail queries so the settings page and the entity's page agree on
 * whether the thread is there.
 *
 * Tasks and queue items are sub-resources, not tools: their threads are part of
 * their own flow and have no switch.
 */
export const useSetToolComments = (
  tool: Tool,
  options?: MutationOpts<ToolCommentSettings, { id: number; disabled: boolean }>
) =>
  useGuildMutation<ToolCommentSettings, { id: number; disabled: boolean }>(
    {
      mutationFn: (guildId, { id, disabled }) =>
        setToolCommentSettingsApiV1GGuildIdToolsToolToolIdCommentsPut(guildId, tool, id, {
          comments_disabled: disabled,
        }),
      invalidate: (_data, vars) => {
        invalidateTool(tool, vars.id);
        // The thread itself: turning the switch back on shows the comments that
        // were there all along, so the cached (refused) read must go.
        void invalidateAllComments();
      },
      errorKey: "common:toolSettings.commentsError",
    },
    options
  );
