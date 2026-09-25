import { useMemo } from "react";

import type { InitiativeRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { useAuth } from "@/hooks/useAuth";
import { type GuildEntry, useGuilds } from "@/hooks/useGuilds";
import { useInitiatives, useInitiativesForGuild } from "@/hooks/useInitiatives";
import { administersGuildContent } from "@/lib/permissions";

const byName = (a: InitiativeRead, b: InitiativeRead) => a.name.localeCompare(b.name);

/**
 * The initiatives to navigate by, from the server's list: the caller's own, or
 * every one a grant reaches — without the archived ones (they stay manageable
 * from guild settings → Initiatives), by name.
 */
export const liveInitiatives = (initiatives: InitiativeRead[] | undefined): InitiativeRead[] =>
  (initiatives ?? []).filter((initiative) => initiative.archived_at === null).sort(byName);

/**
 * Cheap, switcher-entry-only test for whether the user could **author a new
 * top-level tool** somewhere in this guild — used to gate always-mounted
 * surfaces (the global create wizards' entry points and guild pickers) without
 * fetching every guild's initiatives. It never yields a false "cannot": the
 * wizard's own initiative picker reads each initiative's `can.create`. It
 * excludes only the provably-dead guilds — frozen ones, and granted access,
 * which edits what exists and authors nothing.
 */
export const guildMayAuthorTools = (guild: GuildEntry): boolean =>
  !guild.content_read_only && guild.accessType !== "grant";

/**
 * The same for **writing existing content** (e.g. a task inside a project they
 * can write): a read_write grant qualifies. The wizard's project step reads
 * each project's `can.edit`.
 */
export const guildMayWriteContent = (guild: GuildEntry): boolean =>
  !guild.content_read_only &&
  (guild.accessType !== "grant" || guild.grantAccessLevel === "read_write");

/**
 * The active guild's standing as the list pages read it: whether the reader
 * administers its content, and whether they reach it by a grant.
 */
export function useInitiativeAccess() {
  const { activeGuild } = useGuilds();
  return {
    isGuildAdmin: administersGuildContent(activeGuild),
    isGrantGuild: activeGuild?.accessType === "grant",
  };
}

/**
 * Canonical "can the current user create <tool>" answer for pages and create
 * dialogs. Creation always targets an initiative, so the answer has two
 * shapes: with a specific initiative in context (a locked page or a filter
 * selection) it is that initiative's `can.create`; with none (an "All" view)
 * it is "can create in at least one initiative" — the create dialog's
 * initiative picker chooses the target.
 */
export function useToolCreateAccess(
  tool: Tool,
  { initiativeId, enabled }: { initiativeId?: number | null; enabled?: boolean } = {}
) {
  const { user } = useAuth();
  const initiativesQuery = useInitiatives(enabled === undefined ? undefined : { enabled });

  const creatableInitiatives = useMemo(
    () =>
      user ? liveInitiatives(initiativesQuery.data).filter((i) => i.can.create.includes(tool)) : [],
    [user, initiativesQuery.data, tool]
  );

  const canCreate = useMemo(() => {
    if (initiativeId) {
      // Unknown until the list loads — keep create affordances hidden rather
      // than briefly offering a create the server would refuse.
      const initiative = initiativesQuery.data?.find((item) => item.id === initiativeId);
      return Boolean(initiative?.can.create.includes(tool));
    }
    return creatableInitiatives.length > 0;
  }, [initiativeId, initiativesQuery.data, tool, creatableInitiatives]);

  return { canCreate, creatableInitiatives };
}

/**
 * Cross-guild variant for the global create wizards, which pick a guild first:
 * the live initiatives in `guildId` the user can create `tool` in, fetched
 * lazily and sharing the wizard's own query cache.
 */
export function useCreatableInitiatives(tool: Tool, guildId: number | null) {
  const query = useInitiativesForGuild(guildId);
  const initiatives = useMemo(
    () => liveInitiatives(query.data).filter((i) => i.can.create.includes(tool)),
    [query.data, tool]
  );
  return { initiatives, isLoading: query.isLoading };
}

/**
 * Whether the user has anywhere to land the two global create wizards, from the
 * guild switcher alone (no per-guild initiative fetch — this backs always-mounted
 * entry points). `document` follows authoring; `task` follows writing existing
 * content. Both err toward showing the entry.
 */
export function useGlobalCreateAccess() {
  const { guilds } = useGuilds();
  return useMemo(
    () => ({
      document: guilds.some(guildMayAuthorTools),
      task: guilds.some(guildMayWriteContent),
    }),
    [guilds]
  );
}
