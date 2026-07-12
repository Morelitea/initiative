import { useCallback } from "react";

import type { InitiativeRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import {
  isToolEnabled,
  TOOL_REGISTRY,
  TOOLS,
  toolMemberCreateFlag,
  toolMemberViewFlag,
} from "@/lib/tools";

/** What the current user may do with one tool inside an initiative. */
export interface ToolAccess {
  view: boolean;
  create: boolean;
}

/** Per-tool access for an initiative, keyed by the canonical Tool enum. */
export type InitiativeToolAccess = Record<Tool, ToolAccess>;

const byName = (a: InitiativeRead, b: InitiativeRead) => a.name.localeCompare(b.name);

// Full visibility into every tool (gated by the initiative's master
// switches); `canCreate` toggles the create affordances.
const fullAccess = (initiative: InitiativeRead, canCreate: boolean): InitiativeToolAccess =>
  Object.fromEntries(
    TOOLS.map((tool) => {
      const enabled = isToolEnabled(tool, initiative);
      return [tool, { view: enabled, create: canCreate && enabled }];
    })
  ) as InitiativeToolAccess;

// Bare read of the always-visible core tools for someone with no membership
// and no grant — mirrors the historical non-member default.
const readOnlyDefault: InitiativeToolAccess = Object.fromEntries(
  TOOLS.map((tool) => [tool, { view: TOOL_REGISTRY[tool].core, create: false }])
) as InitiativeToolAccess;

/**
 * Centralizes "what initiatives can the current user see, and what can they do
 * in each" for the active guild — accounting for guild-admin and time-bound PAM /
 * break-glass grants in ONE place, so call sites stop re-implementing
 * `initiative.members.some(...)` filters (and stop drifting from each other).
 *
 * Access is exposed per tool (`permissionsFor(initiative)[Tool.queue].view`),
 * derived from the tool registry — a new tool gets its access flags without
 * touching this hook.
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
  // Content writes are frozen server-side (read_only lifecycle status) for
  // real members — admins included. Grant entries never carry the flag (PAM /
  // break-glass override the status), so no accessType check is needed.
  const contentReadOnly = Boolean(activeGuild?.content_read_only);
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

  /** Effective per-tool access for one initiative, keyed by Tool. */
  const permissionsFor = useCallback(
    (initiative: InitiativeRead): InitiativeToolAccess => {
      if (!user) return readOnlyDefault;
      if (isGuildAdmin) return fullAccess(initiative, !contentReadOnly);
      if (isGrantGuild) return fullAccess(initiative, grantReadWrite);
      const membership = initiative.members.find((m) => m.user.id === user.id);
      if (!membership) return readOnlyDefault;
      return Object.fromEntries(
        TOOLS.map((tool) => [
          tool,
          {
            view: Boolean(membership[toolMemberViewFlag(tool)] ?? TOOL_REGISTRY[tool].core),
            create: !contentReadOnly && Boolean(membership[toolMemberCreateFlag(tool)] ?? false),
          },
        ])
      ) as InitiativeToolAccess;
    },
    [user, isGuildAdmin, isGrantGuild, grantReadWrite, contentReadOnly]
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
