import { useCallback } from "react";

import type { InitiativeRead } from "@/api/generated/initiativeAPI.schemas";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import {
  fullToolAccess,
  membershipToolAccess,
  readOnlyToolAccess,
  type ToolAccessMap,
} from "@/lib/tools/registry";

const byName = (a: InitiativeRead, b: InitiativeRead) => a.name.localeCompare(b.name);

/**
 * Centralizes "what initiatives can the current user see, and what can they do
 * in each" for the active guild — accounting for guild-admin and time-bound PAM /
 * break-glass grants in ONE place, so call sites stop re-implementing
 * `initiative.members.some(...)` filters (and stop drifting from each other).
 *
 * `data.bypass` (platform admin/owner) is deliberately NOT a standing access
 * shortcut here: the backend no longer grants ambient cross-guild reach for it
 * (it's the right to break-glass). A platform admin reaches a guild only via a
 * real membership or an active grant — the latter surfaces as
 * `activeGuild.accessType === "grant"` below — so the UI must reflect that and
 * not show create/edit affordances the backend would reject.
 */
export function useInitiativeAccess() {
  const { user } = useAuth();
  const { activeGuild } = useGuilds();

  const isGuildAdmin = activeGuild?.role === "admin";
  const isGrantGuild = activeGuild?.accessType === "grant";
  const grantReadWrite = isGrantGuild && activeGuild?.grantAccessLevel === "read_write";
  // Admins and PAM grantees see every initiative in the guild.
  const seesAllInitiatives = isGuildAdmin || isGrantGuild;

  /** Narrow a guild's initiative list to the ones the user may see. */
  const filterVisible = useCallback(
    (initiatives: InitiativeRead[] | undefined): InitiativeRead[] => {
      if (!user) return [];
      // Archived initiatives are hidden from the main sidebar for everyone
      // (admins included); they stay manageable from guild settings →
      // Initiatives, which reads the unfiltered list directly.
      const source = (initiatives ?? []).filter((initiative) => !initiative.is_archived);
      if (seesAllInitiatives) {
        return source.slice().sort(byName);
      }
      return source
        .filter((initiative) => initiative.members.some((m) => m.user.id === user.id))
        .sort(byName);
    },
    [user, seesAllInitiatives]
  );

  /**
   * Effective per-tool access for one initiative, keyed by `Tool` id. Derived
   * from the tool registry so every tool is covered by construction (and a new
   * tool can't be silently omitted here the way it used to be).
   */
  const permissionsFor = useCallback(
    (initiative: InitiativeRead): ToolAccessMap => {
      if (!user) return readOnlyToolAccess();
      if (isGuildAdmin) return fullToolAccess(initiative, true);
      if (isGrantGuild) return fullToolAccess(initiative, grantReadWrite);
      const membership = initiative.members.find((m) => m.user.id === user.id);
      if (!membership) return readOnlyToolAccess();
      return membershipToolAccess(membership);
    },
    [user, isGuildAdmin, isGrantGuild, grantReadWrite]
  );

  /** Whether the user can manage (PM/admin) a specific initiative. A grant
   * never confers management — those operations are owner/PM-gated. */
  const canManage = useCallback(
    (initiative: InitiativeRead): boolean => {
      if (isGuildAdmin) return true;
      if (!user) return false;
      return initiative.members.some((m) => m.user.id === user.id && m.role === "project_manager");
    },
    [user, isGuildAdmin]
  );

  return { isGuildAdmin, isGrantGuild, grantReadWrite, filterVisible, permissionsFor, canManage };
}
