import { useCallback, useMemo } from "react";

import type { InitiativeRead, Tool, UserRead } from "@/api/generated/initiativeAPI.schemas";
import { useAuth } from "@/hooks/useAuth";
import { type GuildEntry, useGuilds } from "@/hooks/useGuilds";
import { useInitiatives, useInitiativesForGuild } from "@/hooks/useInitiatives";
import { Capability, hasCapability } from "@/lib/permissions";
import {
  CORE_TOOLS,
  isToolEnabled,
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

/** The current user's standing in ONE guild — the admin / grant / break-glass /
 * frozen legs the create logic branches on, resolved from that guild's switcher
 * entry rather than assumed to be the active guild. Deriving these in one place
 * lets both the active-guild hook and the cross-guild wizards share the exact
 * same rule. */
export interface GuildAccessContext {
  isGuildAdmin: boolean;
  isGrantGuild: boolean;
  /** A read_write PAM grant (scoped or break-glass) — clears content-write DAC. */
  grantReadWrite: boolean;
  /** A read_write grant held by a `data.bypass` user: the backend routes it as a
   * synthetic guild admin, so it may author new tools. A scoped read_write grant
   * (no `data.bypass`) may edit existing content but not author — see #881. */
  isBreakGlass: boolean;
  contentReadOnly: boolean;
}

/**
 * Resolve a guild's access context from its switcher entry + the current user.
 * Works for ANY guild, so the active-guild hook and the cross-guild create
 * wizards derive create permission the same way instead of re-implementing the
 * admin / grant / frozen branches.
 */
export function deriveGuildAccess(
  guild: GuildEntry | null | undefined,
  user: Pick<UserRead, "capabilities"> | null | undefined
): GuildAccessContext {
  const isGuildAdmin = guild?.role === "admin";
  const isGrantGuild = guild?.accessType === "grant";
  const grantReadWrite = isGrantGuild && guild?.grantAccessLevel === "read_write";
  const isBreakGlass = grantReadWrite && hasCapability(user, Capability.dataBypass);
  const contentReadOnly = Boolean(guild?.content_read_only);
  return { isGuildAdmin, isGrantGuild, grantReadWrite, isBreakGlass, contentReadOnly };
}

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
  TOOLS.map((tool) => [tool, { view: CORE_TOOLS.has(tool), create: false }])
) as InitiativeToolAccess;

/**
 * Effective per-tool access for one initiative given a resolved guild context —
 * the shared body behind `useInitiativeAccess().permissionsFor` (active guild)
 * and the cross-guild create wizards. Reads server-computed values only: the
 * guild-admin / grant legs, then the membership's `member_tool_flags`.
 */
export function toolAccessForInitiative(
  access: GuildAccessContext,
  initiative: InitiativeRead,
  userId: number
): InitiativeToolAccess {
  const { isGuildAdmin, isGrantGuild, isBreakGlass, contentReadOnly } = access;
  if (isGuildAdmin) return fullAccess(initiative, !contentReadOnly);
  if (isGrantGuild) return fullAccess(initiative, isBreakGlass);
  const membership = initiative.members.find((m) => m.user.id === userId);
  if (!membership) return readOnlyDefault;
  return Object.fromEntries(
    TOOLS.map((tool) => [
      tool,
      {
        view: Boolean(membership[toolMemberViewFlag(tool)] ?? CORE_TOOLS.has(tool)),
        create: !contentReadOnly && Boolean(membership[toolMemberCreateFlag(tool)] ?? false),
      },
    ])
  ) as InitiativeToolAccess;
}

/**
 * Cheap, switcher-entry-only test for whether the user could **author a new
 * top-level tool** (gate 3) somewhere in this guild — used to gate always-mounted
 * surfaces (the global create wizards' entry points and guild pickers) without
 * fetching every guild's initiatives. It never yields a false "cannot": a real
 * member is kept even though the definite answer needs their initiative role, so
 * the wizard's own initiative picker makes the precise call. It excludes only the
 * provably-dead guilds — frozen guilds and scoped PAM grants (which edit existing
 * content but never author, per #881).
 */
export function guildMayAuthorTools(
  guild: GuildEntry,
  user: Pick<UserRead, "capabilities"> | null | undefined
): boolean {
  const a = deriveGuildAccess(guild, user);
  if (a.contentReadOnly) return false;
  if (a.isGuildAdmin) return true;
  if (a.isGrantGuild) return a.isBreakGlass;
  return true; // real member — the precise per-initiative answer is left to the picker
}

/**
 * Cheap, switcher-entry-only test for whether the user could **write existing
 * content** (gate 4 — e.g. create a task inside a project they can write) somewhere
 * in this guild. Unlike authoring, a scoped read_write PAM grant qualifies (its
 * `pam_write` clears content-write DAC). Excludes frozen guilds and read-only
 * grants; a real member is kept (the precise per-project answer is left to the
 * wizard's project step).
 */
export function guildMayWriteContent(
  guild: GuildEntry,
  user: Pick<UserRead, "capabilities"> | null | undefined
): boolean {
  const a = deriveGuildAccess(guild, user);
  if (a.contentReadOnly) return false;
  if (a.isGuildAdmin) return true;
  if (a.isGrantGuild) return a.grantReadWrite;
  return true; // real member — the precise per-project answer is left to the picker
}

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

  const access = useMemo(() => deriveGuildAccess(activeGuild, user), [activeGuild, user]);
  const { isGuildAdmin, isGrantGuild, grantReadWrite } = access;
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
      return toolAccessForInitiative(access, initiative, user.id);
    },
    [user, access]
  );

  /** Whether the user can manage (PM/admin) a specific initiative. A grant
   * never confers management — those operations are owner/PM-gated.
   *
   * Read off `is_manager`, the flag an initiative role actually carries, so an
   * initiative that renamed its managers or added a second managing role counts
   * the same members the server does. */
  const canManage = useCallback(
    (initiative: InitiativeRead): boolean => {
      if (isGuildAdmin) return true;
      if (!user) return false;
      return initiative.members.some((m) => m.user.id === user.id && m.is_manager);
    },
    [user, isGuildAdmin]
  );

  return { isGuildAdmin, isGrantGuild, grantReadWrite, filterVisible, permissionsFor, canManage };
}

/**
 * Canonical "can the current user create <tool>" answer for pages and create
 * dialogs. Creation always targets an initiative, so the answer has two
 * shapes: with a specific initiative in context (a locked page or a filter
 * selection) it is that initiative's server-computed create flag, read via
 * `permissionsFor`; with none (an "All" view) it is "can create in at least
 * one initiative" — the create dialog's initiative picker chooses the target.
 *
 * `creatableInitiatives` backs those pickers: the visible initiatives whose
 * create flag is on for this tool. The flag already folds in the initiative's
 * master switch, so initiatives with the tool disabled drop out.
 */
export function useToolCreateAccess(
  tool: Tool,
  { initiativeId, enabled }: { initiativeId?: number | null; enabled?: boolean } = {}
) {
  const { user } = useAuth();
  const { filterVisible, permissionsFor } = useInitiativeAccess();
  const initiativesQuery = useInitiatives(enabled === undefined ? undefined : { enabled });

  const creatableInitiatives = useMemo(() => {
    if (!user) return [];
    return filterVisible(initiativesQuery.data).filter(
      (initiative) => permissionsFor(initiative)[tool].create
    );
  }, [user, initiativesQuery.data, filterVisible, permissionsFor, tool]);

  const canCreate = useMemo(() => {
    if (initiativeId) {
      const initiative = (initiativesQuery.data ?? []).find((item) => item.id === initiativeId);
      // Unknown until the list loads — keep create affordances hidden rather
      // than briefly offering a create the server would refuse.
      return initiative ? permissionsFor(initiative)[tool].create : false;
    }
    return creatableInitiatives.length > 0;
  }, [initiativeId, initiativesQuery.data, permissionsFor, tool, creatableInitiatives]);

  return { canCreate, creatableInitiatives };
}

/**
 * Cross-guild variant of the create-access derivation, for the global create
 * wizards (which pick a guild first, so `useInitiativeAccess`'s active-guild
 * assumption doesn't hold). Given a specific guild, returns the non-archived
 * initiatives the user can create `tool` in — resolved through the same
 * server-computed rule as the active-guild path. The initiatives are fetched
 * lazily (only when `guildId` is set), sharing the wizard's own query cache.
 */
export function useCreatableInitiatives(tool: Tool, guildId: number | null) {
  const { user } = useAuth();
  const { guilds } = useGuilds();
  const query = useInitiativesForGuild(guildId);

  const initiatives = useMemo(() => {
    if (!user || !guildId) return [];
    const guild = guilds.find((g) => g.id === guildId);
    const access = deriveGuildAccess(guild, user);
    return (query.data ?? [])
      .filter((initiative) => !initiative.is_archived)
      .filter((initiative) => toolAccessForInitiative(access, initiative, user.id)[tool].create)
      .sort(byName);
  }, [user, guildId, guilds, query.data, tool]);

  return { initiatives, isLoading: query.isLoading };
}

/**
 * Whether the user has anywhere to land the two global create wizards, from the
 * guild switcher alone (no per-guild initiative fetch — this backs always-mounted
 * entry points). `document` follows the authoring gate (gate 3); `task` follows
 * the content-write gate (gate 4). Both err toward showing the entry: they hide
 * only when every guild is provably dead (frozen or, for authoring, a scoped PAM
 * grant), and the wizards' own pickers make the precise per-initiative call.
 */
export function useGlobalCreateAccess() {
  const { user } = useAuth();
  const { guilds } = useGuilds();

  return useMemo(
    () => ({
      document: guilds.some((guild) => guildMayAuthorTools(guild, user)),
      task: guilds.some((guild) => guildMayWriteContent(guild, user)),
    }),
    [guilds, user]
  );
}
