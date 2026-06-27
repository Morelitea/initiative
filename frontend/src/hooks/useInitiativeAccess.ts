import { useCallback } from "react";

import type { InitiativeRead } from "@/api/generated/initiativeAPI.schemas";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";

/** What an initiative's sidebar/sections expose to the current user. */
export interface InitiativeSectionPermissions {
  canViewDocs: boolean;
  canViewProjects: boolean;
  canViewQueues: boolean;
  canViewEvents: boolean;
  canViewAdvancedTool: boolean;
  canViewCounters: boolean;
  canCreateDocs: boolean;
  canCreateProjects: boolean;
  canCreateQueues: boolean;
  canCreateEvents: boolean;
  canCreateCounters: boolean;
}

const byName = (a: InitiativeRead, b: InitiativeRead) => a.name.localeCompare(b.name);

// Full visibility into every section (gated by the initiative's feature
// flags); `canCreate` toggles the create affordances.
const fullAccess = (
  initiative: InitiativeRead,
  canCreate: boolean
): InitiativeSectionPermissions => ({
  canViewDocs: true,
  canViewProjects: true,
  canViewQueues: initiative.queues_enabled ?? false,
  canViewEvents: initiative.events_enabled ?? false,
  canViewAdvancedTool: initiative.advanced_tool_enabled ?? false,
  canViewCounters: initiative.counters_enabled ?? false,
  canCreateDocs: canCreate,
  canCreateProjects: canCreate,
  canCreateQueues: canCreate && (initiative.queues_enabled ?? false),
  canCreateEvents: canCreate && (initiative.events_enabled ?? false),
  canCreateCounters: canCreate && (initiative.counters_enabled ?? false),
});

// Bare read of the always-visible sections (docs/projects) for someone with no
// membership and no grant — mirrors the historical non-member default.
const readOnlyDefault: InitiativeSectionPermissions = {
  canViewDocs: true,
  canViewProjects: true,
  canViewQueues: false,
  canViewEvents: false,
  canViewAdvancedTool: false,
  canViewCounters: false,
  canCreateDocs: false,
  canCreateProjects: false,
  canCreateQueues: false,
  canCreateEvents: false,
  canCreateCounters: false,
};

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

  /** Effective per-section permissions for one initiative. */
  const permissionsFor = useCallback(
    (initiative: InitiativeRead): InitiativeSectionPermissions => {
      if (!user) return readOnlyDefault;
      if (isGuildAdmin) return fullAccess(initiative, true);
      if (isGrantGuild) return fullAccess(initiative, grantReadWrite);
      const membership = initiative.members.find((m) => m.user.id === user.id);
      if (!membership) return readOnlyDefault;
      return {
        canViewDocs: membership.can_view_docs ?? true,
        canViewProjects: membership.can_view_projects ?? true,
        canViewQueues: membership.can_view_queues ?? false,
        canViewEvents: membership.can_view_events ?? false,
        canViewAdvancedTool: membership.can_view_advanced_tool ?? false,
        canViewCounters: membership.can_view_counters ?? false,
        canCreateDocs: membership.can_create_docs ?? false,
        canCreateProjects: membership.can_create_projects ?? false,
        canCreateQueues: membership.can_create_queues ?? false,
        canCreateEvents: membership.can_create_events ?? false,
        canCreateCounters: membership.can_create_counters ?? false,
      };
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
