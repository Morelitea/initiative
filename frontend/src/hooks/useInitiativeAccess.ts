import { useMemo } from "react";

import type { InitiativeRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { useAuth } from "@/hooks/useAuth";
import { type CommunityEntry, useCommunities } from "@/hooks/useCommunities";
import { useInitiatives, useInitiativesForCommunity } from "@/hooks/useInitiatives";

const byName = (a: InitiativeRead, b: InitiativeRead) => a.name.localeCompare(b.name);

/**
 * The initiatives to navigate by, from the server's list: the caller's own, or
 * every one a grant reaches — without the archived ones (they stay manageable
 * from community settings → Initiatives), by name.
 */
export const liveInitiatives = (initiatives: InitiativeRead[] | undefined): InitiativeRead[] =>
  (initiatives ?? []).filter((initiative) => initiative.archived_at === null).sort(byName);

/**
 * Cheap, switcher-entry-only test for whether the user could **author a new
 * top-level tool** somewhere in this community — used to gate always-mounted
 * surfaces (the global create wizards' entry points and community pickers) without
 * fetching every community's initiatives. It never yields a false "cannot": the
 * wizard's own initiative picker reads each initiative's `can.create`. It
 * excludes only the provably-dead communities — frozen ones, and granted access,
 * which edits what exists and authors nothing.
 */
export const communityMayAuthorTools = (community: CommunityEntry): boolean =>
  !community.content_read_only && community.accessType !== "grant";

/**
 * The same for **writing existing content** (e.g. a task inside a project they
 * can write): a read_write grant qualifies. The wizard's project step reads
 * each project's `can.edit`.
 */
export const communityMayWriteContent = (community: CommunityEntry): boolean =>
  !community.content_read_only &&
  (community.accessType !== "grant" || community.grantAccessLevel === "read_write");

/**
 * The active community's standing as the list pages read it: whether the reader
 * administers its content, and whether they reach it by a grant.
 */
export function useInitiativeAccess() {
  const { activeCommunity } = useCommunities();
  return {
    isCommunityAdmin: Boolean(activeCommunity?.can.administer_content),
    isGrantCommunity: activeCommunity?.accessType === "grant",
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
 * Cross-community variant for the global create wizards, which pick a community first:
 * the live initiatives in `communityId` the user can create `tool` in — or every
 * live one when `tool` is null, for a wizard that writes into existing content
 * — fetched lazily and sharing the wizard's own query cache.
 */
export function useCreatableInitiatives(tool: Tool | null, communityId: number | null) {
  const query = useInitiativesForCommunity(communityId);
  const initiatives = useMemo(
    () => liveInitiatives(query.data).filter((i) => tool === null || i.can.create.includes(tool)),
    [query.data, tool]
  );
  return { initiatives, isLoading: query.isLoading };
}

/**
 * Whether the user has anywhere to land the two global create wizards, from the
 * community switcher alone (no per-community initiative fetch — this backs always-mounted
 * entry points). `tool` follows authoring a tool; `task` follows writing
 * existing content. Both err toward showing the entry.
 */
export function useGlobalCreateAccess() {
  const { communities } = useCommunities();
  return useMemo(
    () => ({
      tool: communities.some(communityMayAuthorTools),
      task: communities.some(communityMayWriteContent),
    }),
    [communities]
  );
}
