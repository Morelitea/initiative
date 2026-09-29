import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { TOOL_HOOKS } from "@/hooks/toolHooks";
import { useGuildMutation } from "@/hooks/useApiMutation";

/** All a tool needs to exist: a name, and where it lives. */
interface NewTool {
  tool: Tool;
  name: string;
  initiativeId: number;
}

/**
 * Making any tool, when which one is only known at the moment it is made.
 *
 * The same create every tool's table entry in `TOOL_HOOKS` carries, and the
 * same lists refreshed afterwards, so this is that path with the tool chosen
 * late rather than a second way in.
 */
export const useCreateTool = () =>
  useGuildMutation<{ id: number }, NewTool>({
    mutationFn: (guildId, { tool, name, initiativeId }) =>
      TOOL_HOOKS[tool].create(guildId, { name, initiative_id: initiativeId }),
    invalidate: (_made, { tool }) => invalidate(q.toolList(tool)),
  });
