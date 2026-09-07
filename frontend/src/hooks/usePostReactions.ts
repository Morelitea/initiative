import type { PostReactionSettings } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { setPostReactionSettingsApiV1GGuildIdPostsPostIdReactionsPut } from "@/api/generated/posts/posts";
import { invalidateTool } from "@/api/query-keys";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

/**
 * The reactions switch on one notice.
 *
 * There is no generic route behind this the way there is for comments: a post
 * is the only thing that takes reactions of its own, so the mutation names it.
 * Invalidates the post's list + detail queries, because the board renders the
 * bar from the row it already has.
 */
export const useSetPostReactions = (
  options?: MutationOpts<PostReactionSettings, { id: number; enabled: boolean }>
) =>
  useGuildMutation<PostReactionSettings, { id: number; enabled: boolean }>(
    {
      mutationFn: (guildId, { id, enabled }) =>
        setPostReactionSettingsApiV1GGuildIdPostsPostIdReactionsPut(guildId, id, {
          reactions_enabled: enabled,
        }),
      invalidate: (_data, vars) => {
        invalidateTool(Tool.post, vars.id);
      },
      errorKey: "common:toolSettings.reactionsError",
    },
    options
  );
