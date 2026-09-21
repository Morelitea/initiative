/**
 * The rows one command-palette group browses.
 *
 * Takes a tool's own `listQuery` from `TOOL_HOOKS` rather than the tool, so
 * each entry in `lib/toolPalette` keeps its list's exact item type — and with
 * it the fields that entry maps. Reading the tool's declared query means a
 * group shares a cache entry with the list page it mirrors instead of asking
 * the same endpoint under a key of its own.
 *
 * The stale time is the palette's, not the tool's: a dropdown of names does
 * not need to be a minute fresher than the list it is drawn from.
 */

import { useQuery } from "@tanstack/react-query";

import type { ToolListParams } from "@/hooks/toolHooks";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";

export interface ToolPaletteListOptions {
  /** Only fetch while the palette is open for an authenticated user. */
  enabled: boolean;
}

export const useToolPaletteList = <TPage>(
  listQuery: (
    guildId: number,
    params?: ToolListParams
  ) => { queryKey: readonly unknown[]; queryFn: () => Promise<TPage> },
  params: ToolListParams | undefined,
  { enabled }: ToolPaletteListOptions
) => {
  const guildId = useActiveGuildId();
  return useQuery({ ...listQuery(guildId, params), enabled, staleTime: 60_000 });
};
