/**
 * What every initiative-settings screen needs to know before it renders: which
 * initiative is being configured, whether it exists, and what this reader may
 * do to it.
 *
 * The settings sections are separate routes, so each one resolves this for
 * itself rather than receiving it through the layout — it is a cached query, so
 * asking again costs nothing and no page depends on props it can't see in its
 * own file.
 */

import { useParams } from "@tanstack/react-router";

import type { InitiativeRead } from "@/api/generated/initiativeAPI.schemas";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { useInitiative } from "@/hooks/useInitiatives";

export interface InitiativeSettingsContext {
  /** The id from the path; 0 when the path doesn't carry a usable one. */
  initiativeId: number;
  hasValidInitiativeId: boolean;
  /** The initiative, once it has landed and it is one the reader may see. */
  initiative: InitiativeRead | null;
  isLoading: boolean;
  isGuildAdmin: boolean;
  /** Manage the roster, roles, details — the standing every section requires. */
  canManageMembers: boolean;
  /** Deleting is the guild admin's alone, even among managers. */
  canDeleteInitiative: boolean;
}

export function useInitiativeSettings(): InitiativeSettingsContext {
  const { initiativeId: initiativeIdParam } = useParams({ strict: false }) as {
    initiativeId?: string;
  };
  const parsedInitiativeId = Number(initiativeIdParam);
  const hasValidInitiativeId = Boolean(initiativeIdParam) && Number.isFinite(parsedInitiativeId);
  const initiativeId = hasValidInitiativeId ? parsedInitiativeId : 0;

  const { user } = useAuth();
  const { activeGuild } = useGuilds();
  // Addressed by id, not picked out of the caller's own list: a guild admin
  // reaches every initiative in their guild whether or not they have joined it,
  // and the endpoint answers 404 to anyone the row is not visible to.
  const initiativeQuery = useInitiative(hasValidInitiativeId ? initiativeId : null);
  const initiative = initiativeQuery.data ?? null;

  const isGuildAdmin = activeGuild?.role === "admin";
  const membership = initiative?.members.find((member) => member.user.id === user?.id);
  const isInitiativeManager = Boolean(membership?.is_manager);

  return {
    initiativeId,
    hasValidInitiativeId,
    initiative,
    isLoading: initiativeQuery.isLoading,
    isGuildAdmin,
    canManageMembers: Boolean(isGuildAdmin || isInitiativeManager),
    canDeleteInitiative: Boolean(isGuildAdmin),
  };
}
