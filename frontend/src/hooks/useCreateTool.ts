import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { apiMutator } from "@/api/mutator";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toolApiPath, toolRouteSegment } from "@/lib/tools";

/** All a tool needs to exist: a name, and where it lives. */
export interface NewTool {
  tool: Tool;
  name: string;
  initiativeId: number;
}

/**
 * Making any tool, derived from the enum.
 *
 * Every tool is created the same way — POST a name and an initiative to its own
 * collection — so this needs no line per tool and gains a seventh the day the
 * enum does. The path comes from `toolApiPath`, which every other tool surface
 * already builds its URLs from.
 *
 * It deliberately does NOT go through the six generated `useCreateX` hooks. One
 * per tool is one to forget, and forgetting would mean a tool that quietly
 * cannot be made rather than one that visibly cannot compile.
 */
export const useCreateTool = () => {
  const guildId = useActiveGuildId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ tool, name, initiativeId }: NewTool) =>
      apiMutator<{ id: number }>({
        url: `/api/v1/g/${guildId}${toolApiPath(tool).replace("/api/v1", "")}/`,
        method: "POST",
        data: { name, initiative_id: initiativeId },
      }),
    onSuccess: (_made, { tool }) => {
      // Whatever lists this tool, refreshed — matched on the tool's own path
      // segment, so this is derived too rather than a set of keys to maintain.
      const segment = toolRouteSegment(tool);
      void queryClient.invalidateQueries({
        predicate: (query) => JSON.stringify(query.queryKey).includes(segment),
      });
    },
  });
};
