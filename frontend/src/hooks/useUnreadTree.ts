import { useMemo } from "react";

import { useUnreadPlaces } from "@/hooks/useNotifications";

/**
 * Where there is unread activity, as questions the navigation can ask.
 *
 * The server returns a set of places — (community, initiative, tool), each
 * level independently optional. A node shows a dot when any place names it as
 * an ancestor, so the rollup needs no rolling up: a notification belonging to
 * no initiative still carries its community, which lights the community and
 * nothing beneath it.
 *
 * Deliberately dots, never counts. A count invites you to zero it, and carried
 * three levels deep it turns into arithmetic nobody asked for when the only
 * question being asked is "where do I go".
 */
export const useUnreadTree = (options?: { enabled?: boolean }) => {
  const { data } = useUnreadPlaces({ enabled: options?.enabled });

  return useMemo(() => {
    const places = data?.places ?? [];
    const guilds = new Set<number>();
    const initiatives = new Set<number>();
    const tools = new Set<string>();

    for (const place of places) {
      if (place.guild_id != null) guilds.add(place.guild_id);
      if (place.initiative_id != null) initiatives.add(place.initiative_id);
      // A tool is only meaningful inside its initiative, so the key carries
      // both — two initiatives each with a busy Projects tool must not light
      // each other.
      if (place.initiative_id != null && place.tool) {
        tools.add(`${place.initiative_id}:${place.tool}`);
      }
    }

    return {
      /** Anything at all, anywhere — what the bell's dot reads. */
      hasAny: places.length > 0,
      hasGuild: (guildId: number | null | undefined) => guildId != null && guilds.has(guildId),
      hasInitiative: (initiativeId: number | null | undefined) =>
        initiativeId != null && initiatives.has(initiativeId),
      hasTool: (initiativeId: number | null | undefined, tool: string | null | undefined) =>
        initiativeId != null && Boolean(tool) && tools.has(`${initiativeId}:${tool}`),
    };
  }, [data]);
};
