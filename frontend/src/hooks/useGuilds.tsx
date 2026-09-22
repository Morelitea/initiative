// The UI calls a guild a community — see the NAMING note in `@/api/query-keys`.
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { apiClient } from "@/api/client";
import type { AccessGrantRead, GuildRead } from "@/api/generated/initiativeAPI.schemas";
import { resetGuildScopedQueries, setInvalidationGuild } from "@/api/query-keys";
import { useAuth } from "@/hooks/useAuth";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { persistGuildId, readStoredGuildId, readStoredGuildIdFor } from "@/lib/activeGuildStorage";
import { renderableBanner } from "@/lib/banner";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import {
  addGrantOnlyGuildIds,
  hydrateGuildShard,
  isOfflineCacheEnabled,
  retainOnlyGuilds,
  setGrantOnlyGuildIds,
} from "@/lib/offlineCache";
import {
  currentServerKey,
  isNoAnswerError,
  readOfflineGuilds,
  saveOfflineGuilds,
} from "@/lib/offlineSession";

/**
 * A guild entry in the switcher. Member guilds come from `/guilds/`; entries
 * the user can only reach via a live, time-bound PAM access grant are
 * synthesized from `/access-grants/` and flagged with `accessType: "grant"`
 * so the UI can mark them temporary and enforce read-only.
 */
export type GuildEntry = GuildRead & {
  accessType?: "member" | "grant";
  grantExpiresAt?: string | null;
  /** The content rung of the grant this guild is reached by. A settings grant
   *  carries its own vocabulary in the same field, and never gets here — a
   *  guild reached only by one confers no content access to gate. */
  grantAccessLevel?: string | null;
  /** The separate settings rung held for this community. It never confers
   * content access and must not be represented as a roster role. */
  grantSettingsLevel?: "admin" | "superadmin" | null;
  /** Whether this entry reaches the community's work at all. A settings-only
   * grant does not — the server refuses every content route for one — so the
   * surfaces built on content are not offered with it. Absent means yes,
   * which is what a membership is. */
  reachesContent?: boolean;
};

interface GuildContextValue {
  guilds: GuildEntry[];
  /** This tab's guild, taken from its `/c/{guildId}` URL (the route layout
   * calls syncGuildFromUrl). Per-tab — no server-held context — so two tabs can
   * sit in two different guilds at once. */
  activeGuildId: number | null;
  activeGuild: GuildEntry | null;
  /** True when the active guild is reached via a read-only grant — writes are
   * blocked server-side, so the UI should hide write affordances. */
  activeGuildReadOnly: boolean;
  loading: boolean;
  error: string | null;
  refreshGuilds: () => Promise<GuildEntry[]>;
  switchGuild: (guildId: number) => Promise<void>;
  syncGuildFromUrl: (guildId: number) => Promise<void>;
  createGuild: (input: { name: string; description?: string }) => Promise<GuildRead>;
  updateGuildInState: (guild: GuildRead) => void;
  reorderGuilds: (guildIds: number[]) => void;
  canCreateGuilds: boolean;
}

export const GuildContext = createContext<GuildContextValue | undefined>(undefined);

const sortGuilds = (guildList: GuildEntry[]): GuildEntry[] => {
  return [...guildList].sort((a, b) => {
    // Grant (temporary) guilds always sort after member guilds.
    const aGrant = a.accessType === "grant" ? 1 : 0;
    const bGrant = b.accessType === "grant" ? 1 : 0;
    if (aGrant !== bGrant) {
      return aGrant - bGrant;
    }
    const positionDelta = (a.position ?? 0) - (b.position ?? 0);
    if (positionDelta !== 0) {
      return positionDelta;
    }
    return a.id - b.id;
  });
};

/** Build a synthetic switcher entry for a guild reachable only via live grants. */
const settingsGrantLevel = (grant?: AccessGrantRead): "admin" | "superadmin" | null =>
  grant?.access_level === "admin" || grant?.access_level === "superadmin"
    ? grant.access_level
    : null;

const grantEntry = (grant: AccessGrantRead, settingsGrant?: AccessGrantRead): GuildEntry => ({
  id: grant.guild_id,
  name: grant.guild_name ?? `Guild #${grant.guild_id}`,
  description: null,
  icon_url: null,
  // A blank banner until the guild's own payload arrives with the real one.
  banner: renderableBanner(),
  // Nobody is "here" in a guild reached only by a grant until its own payload
  // arrives and says so.
  online_count: 0,
  role: "member",
  // What this grant reaches, as the server answered it on the grant itself —
  // the same two questions a guild's own payload answers, so a screen asks
  // one question whichever way the community was reached.
  is_admin: settingsGrant?.administers_guild ?? false,
  holds_seat: settingsGrant?.holds_guild_seat ?? false,
  // A settings grant carries no content access; a content grant is what does.
  reachesContent: grant.purpose === "content",
  position: Number.MAX_SAFE_INTEGER,
  retention_days: null,
  max_storage_bytes: null,
  max_users: null,
  member_count: 0,
  tier_name: null,
  // The guild's lifecycle status, so an operator on a grant sees a suspended /
  // read-only guild they're acting in (the access banner surfaces it).
  status: grant.guild_status,
  // PAM/break-glass overrides the lifecycle status — a grantee's writability
  // comes from the grant level, never from the guild being frozen.
  content_read_only: false,
  // Admin-only entitlements; a grantee acts as a member here, so they're absent.
  auth_options: null,
  // Likewise: these settings are not inferred into a synthetic entry. An
  // authorized settings grantee reads their real values from the dedicated
  // settings endpoint when opening Authentication.
  allow_api_keys: null,
  enforce_compliance_session: null,
  require_second_factor: null,
  // A grant reaches one named guild directly; the directory is not how the
  // grantee got here, and this synthetic entry is never listed in it.
  is_community: false,
  categories: [],
  // Whether a guild shows real names is the guild's own setting; a synthetic
  // entry has no row to read it from, so it takes the default — handles.
  show_member_names: false,
  // Guild-admin territory, and a grantee acts as a member — so, unanswered.
  has_adult_content: null,
  created_at: grant.requested_at,
  updated_at: grant.requested_at,
  accessType: "grant",
  grantExpiresAt: grant.expires_at,
  grantAccessLevel: grant.purpose === "content" ? grant.access_level : null,
  grantSettingsLevel: settingsGrantLevel(settingsGrant),
});

export const GuildProvider = ({ children }: { children: ReactNode }) => {
  const { user, refreshUser } = useAuth();
  const { isOnline } = useNetworkStatus();
  const [guilds, setGuilds] = useState<GuildEntry[]>([]);
  const [activeGuildId, setActiveGuildId] = useState<number | null>(readStoredGuildId);
  // Start as true - we're loading until first fetch completes (or until we know we shouldn't fetch)
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const reorderDebounceRef = useRef<number | null>(null);
  const pendingOrderRef = useRef<number[] | null>(null);
  const hasFetchedRef = useRef(false);
  /** True while the switcher is showing the list this device remembered rather
   *  than one the server gave us. */
  const showingRememberedGuildsRef = useRef(false);
  const activeGuildIdRef = useRef(activeGuildId);
  activeGuildIdRef.current = activeGuildId;
  // Mirror the active guild to the invalidation layer synchronously on every
  // render (same pattern as the ref above) so guild-scoped invalidation is
  // scoped from the very FIRST render — `activeGuildId` is seeded from storage
  // by useState, so deferring this to an effect would leave a one-render window
  // where a mutation's onSuccess falls through to matching all guilds. Per-tab:
  // a module var is per-JS-context (see query-keys.ts).
  setInvalidationGuild(activeGuildId);

  // Key guild loading on the user's *id*, not the user object: `refreshUser()`
  // always returns a fresh object, so an object-identity dep would refetch the
  // guild list and access grants on every profile refresh.
  const userId = user?.id ?? null;
  // Mirrored synchronously so a reply that was asked for on behalf of somebody
  // else can be recognised as such when it lands. Reads outlive the person they
  // were made for: signing out, or switching account, does not cancel a request
  // already in the air, and acting on one now means pruning this device's cache
  // against the previous user's memberships.
  const userIdRef = useRef(userId);
  userIdRef.current = userId;

  const canCreateGuilds = user?.can_create_guilds ?? true;

  // Persist this tab's guild as the fresh-tab default (read once at mount),
  // under the account it belongs to: a browser is shared, and the next account
  // to sign in here has its own answer.
  useEffect(() => {
    persistGuildId(activeGuildId, userId);
  }, [activeGuildId, userId]);

  const applyGuildState = useCallback(
    (guildList: GuildEntry[], grantsKnown = true, forUserId: number | null = null) => {
      const sortedGuilds = sortGuilds(guildList);
      setGuilds(sortedGuilds);

      // Content from a guild reached only by a time-bound grant is not written to
      // the offline cache, and this is the only place that knows which guilds
      // those are. When the grant list could not be read, the set is widened
      // rather than replaced — an incomplete reading must not shrink it.
      const grantIds = sortedGuilds
        .filter((guild) => guild.accessType === "grant")
        .map((guild) => guild.id);
      if (grantsKnown) {
        setGrantOnlyGuildIds(grantIds);
      } else {
        addGrantOnlyGuildIds(grantIds);
      }

      // Use functional update to avoid overriding in-flight guild switches.
      // Only change activeGuildId when the current value is no longer valid.
      setActiveGuildId((prev) => {
        if (prev !== null && sortedGuilds.some((guild) => guild.id === prev)) {
          return prev;
        }

        // Fall back to what THIS account last had open, not whoever used the
        // browser before them.
        const stored = readStoredGuildIdFor(forUserId);
        if (stored && sortedGuilds.some((guild) => guild.id === stored)) {
          return stored;
        }

        // Last resort: first available guild
        return sortedGuilds[0]?.id ?? null;
      });
    },
    []
  );

  /** Reload the guild list, and hand it back: sign-in has to know what this
   *  account can reach before it decides where to land them. */
  const refreshGuilds = useCallback(async (): Promise<GuildEntry[]> => {
    if (userId === null) {
      setGuilds([]);
      setActiveGuildId(null);
      setError(null);
      setLoading(false);
      return [];
    }

    // Only show loading indicator on initial load, not background refreshes
    if (!hasFetchedRef.current) setLoading(true);

    setError(null);
    const forUser = userId;
    try {
      const response = await apiClient.get<GuildRead[]>("/guilds/");
      if (userIdRef.current !== forUser) return [];
      hasFetchedRef.current = true;

      // Also surface guilds the user can only reach via a live PAM grant, so
      // they appear in the switcher (flagged temporary) and can actually be
      // entered. Best-effort: a failure here must not break the guild list.
      const memberIds = new Set(response.data.map((g) => g.id));
      let grantGuilds: GuildEntry[] = [];
      let grantsKnown = true;
      const liveByGuild = new Map<
        number,
        { content?: AccessGrantRead; settings?: AccessGrantRead }
      >();
      try {
        const grants = await apiClient.get<AccessGrantRead[]>("/access-grants/", {
          params: { mine: true },
        });
        for (const grant of grants.data) {
          if (!grant.is_live || (grant.purpose !== "content" && grant.purpose !== "settings")) {
            continue;
          }
          const pair = liveByGuild.get(grant.guild_id) ?? {};
          const purpose = grant.purpose;
          const existing = pair[purpose];
          if (!existing || (grant.expires_at ?? "") > (existing.expires_at ?? "")) {
            pair[purpose] = grant;
            liveByGuild.set(grant.guild_id, pair);
          }
        }
        grantGuilds = Array.from(liveByGuild.entries()).flatMap(
          ([guildId, { content, settings }]) => {
            if (memberIds.has(guildId)) return [];
            if (content) return [grantEntry(content, settings)];
            return settings ? [grantEntry(settings, settings)] : [];
          }
        );
      } catch (grantErr) {
        grantsKnown = false;
        console.error("Failed to load access grants for guild switcher", grantErr);
      }

      // The grants call is a second wait, and the account can change across it.
      if (userIdRef.current !== forUser) return [];

      if (isOfflineCacheEnabled()) {
        // Only real memberships are remembered for offline use: a guild reached
        // by a grant has no cached content to open, and the grant may be over
        // by the time the device is looked at again.
        saveOfflineGuilds(response.data, currentServerKey());
        showingRememberedGuildsRef.current = false;
        // Both lists have to be the server's answer before anything is thrown
        // away. Without the grants half we cannot tell a community somebody has
        // left from one they are in the middle of using on a grant, so an
        // incomplete read prunes nothing and the next good one does it.
        if (grantsKnown) {
          const memberships = [...memberIds];
          await retainOnlyGuilds(
            [...memberships, ...grantGuilds.map((guild) => guild.id)],
            memberships
          );
        }
      }

      const memberGuilds = response.data.map(
        (guild): GuildEntry => ({
          ...guild,
          grantSettingsLevel: settingsGrantLevel(liveByGuild.get(guild.id)?.settings),
        })
      );
      applyGuildState([...memberGuilds, ...grantGuilds], grantsKnown, forUser);
      return [...memberGuilds, ...grantGuilds];
    } catch (err) {
      if (userIdRef.current !== forUser) return [];
      // Nothing answered: fall back to the communities this device last saw, so
      // the switcher is populated and the pages it still holds can be opened.
      // The grant list is unknown here, so the exclusion set is only widened.
      if (isOfflineCacheEnabled() && isNoAnswerError(err)) {
        const remembered = readOfflineGuilds<GuildEntry>(currentServerKey());
        if (remembered && remembered.length > 0) {
          hasFetchedRef.current = true;
          showingRememberedGuildsRef.current = true;
          applyGuildState(remembered, false, forUser);
          setLoading(false);
          return remembered;
        }
      }
      console.error("Failed to load guilds", err);
      // Fallback lives in the ``errors`` namespace (preloaded at init) rather
      // than ``guilds``: this hook never mounts a ``useTranslation("guilds")``,
      // so on a startup fetch failure that namespace may not be loaded yet.
      setError(getErrorMessage(err, "errors:unableToLoadGuilds"));
      return [];
    } finally {
      // Not for a reply that belongs to somebody else: the request for whoever
      // is here now is still running, and its loading state is not ours to end.
      if (userIdRef.current === forUser) setLoading(false);
    }
  }, [userId, applyGuildState]);

  const flushPendingOrder = useCallback(async () => {
    if (!pendingOrderRef.current) {
      return;
    }
    const payload = pendingOrderRef.current;
    pendingOrderRef.current = null;
    try {
      await apiClient.put("/guilds/order", { guildIds: payload });
    } catch (err) {
      console.error("Failed to save guild order", err);
      toast.error("Unable to save community order. Refreshing…");
      await refreshGuilds();
    }
  }, [refreshGuilds]);

  const scheduleOrderSave = useCallback(
    (guildIds: number[]) => {
      if (guildIds.length === 0) {
        return;
      }
      pendingOrderRef.current = guildIds;
      if (typeof window === "undefined") {
        void flushPendingOrder();
        return;
      }
      if (reorderDebounceRef.current) {
        window.clearTimeout(reorderDebounceRef.current);
      }
      reorderDebounceRef.current = window.setTimeout(() => {
        reorderDebounceRef.current = null;
        void flushPendingOrder();
      }, 500);
    },
    [flushPendingOrder]
  );

  useEffect(() => {
    return () => {
      if (typeof window !== "undefined" && reorderDebounceRef.current) {
        window.clearTimeout(reorderDebounceRef.current);
      }
      if (pendingOrderRef.current) {
        void flushPendingOrder();
      }
    };
  }, [flushPendingOrder]);

  useEffect(() => {
    if (userId === null) {
      setGuilds([]);
      setActiveGuildId(null);
      setError(null);
      setLoading(false);
      hasFetchedRef.current = false;
      showingRememberedGuildsRef.current = false;
      return;
    }
    void refreshGuilds();
  }, [userId, refreshGuilds]);

  // A remembered list is only ever a stand-in. Signal returning is the moment
  // to replace it — nothing else would, since the list is fetched off the
  // user's id and that has not changed.
  useEffect(() => {
    if (!isOnline || !showingRememberedGuildsRef.current) return;
    void refreshGuilds();
  }, [isOnline, refreshGuilds]);

  const switchGuild = useCallback(
    async (guildId: number) => {
      // The guild lives in the URL: callers navigate to /c/{guildId} and the
      // route layout calls syncGuildFromUrl. Here we just move this tab's local
      // state and drop the previous guild's now-wrong cached query data. No
      // server context — per-tab only, so two tabs can hold different guilds.
      if (userId === null || guildId === activeGuildIdRef.current) {
        return;
      }
      setActiveGuildId(guildId);
      await resetGuildScopedQueries(guildId);
      await hydrateGuildShard(guildId);
      await Promise.all([refreshGuilds(), refreshUser()]);
    },
    [userId, refreshGuilds, refreshUser]
  );

  /**
   * Adopt the guild from a /c/{guildId} route into this tab's local state
   * (rail highlight, redirect targets, query keys). Per-tab only — no server
   * context — so each tab tracks the guild in its own URL.
   */
  const syncGuildFromUrl = useCallback(async (guildId: number) => {
    if (guildId === activeGuildIdRef.current) {
      return;
    }
    setActiveGuildId(guildId);
    persistGuildId(guildId, userId);
    await resetGuildScopedQueries(guildId);
    // Only the default community is hydrated at startup, so one opened later
    // brings its own cached content with it.
    await hydrateGuildShard(guildId);
  }, []);

  // Each browser tab holds its OWN guild, taken from its `/c/{guildId}` URL —
  // tabs do NOT converge. We deliberately do not listen for the guild storage
  // event, so a guild switch in one tab never drags another tab's context with
  // it; that is what lets two tabs sit in two different guilds at once. (The
  // persisted id is only a fresh-tab default, read once at mount.)

  const reorderGuilds = useCallback(
    (guildIds: number[]) => {
      if (guildIds.length === 0) {
        return;
      }
      if (guilds.length <= 1) {
        return;
      }
      const uniqueIds: number[] = [];
      const seenIds = new Set<number>();
      for (const id of guildIds) {
        if (seenIds.has(id)) {
          continue;
        }
        seenIds.add(id);
        uniqueIds.push(id);
      }
      setGuilds((prev) => {
        if (prev.length <= 1) {
          return prev;
        }
        const lookup = new Map(prev.map((guild) => [guild.id, guild]));
        const ordered: GuildRead[] = [];
        uniqueIds.forEach((id) => {
          const match = lookup.get(id);
          if (match) {
            ordered.push({ ...match });
            lookup.delete(id);
          }
        });
        ordered.push(...Array.from(lookup.values()).map((guild) => ({ ...guild })));
        const withPositions = ordered.map((guild, index) => ({
          ...guild,
          position: index,
        }));
        return sortGuilds(withPositions);
      });
      scheduleOrderSave(uniqueIds);
    },
    [guilds.length, scheduleOrderSave]
  );

  const createGuild = useCallback(
    async ({ name, description }: { name: string; description?: string }) => {
      if (userId === null) {
        throw new Error("You must be signed in to create a community.");
      }
      if (!canCreateGuilds) {
        throw new Error("Community creation is disabled.");
      }

      const trimmedName = name.trim();
      if (!trimmedName) {
        throw new Error("Community name is required.");
      }

      const response = await apiClient.post<GuildRead>("/guilds/", {
        name: trimmedName,
        description: description?.trim() || undefined,
      });

      await Promise.all([refreshGuilds(), refreshUser()]);

      return response.data;
    },
    [userId, canCreateGuilds, refreshGuilds, refreshUser]
  );

  const updateGuildInState = useCallback((guild: GuildRead) => {
    setGuilds((prev) => {
      let replaced = false;
      const next = prev.map((existing) => {
        if (existing.id === guild.id) {
          replaced = true;
          return guild;
        }
        return existing;
      });
      const merged = replaced ? next : next.concat(guild);
      return sortGuilds(merged);
    });
  }, []);

  const activeGuild = useMemo(
    () => guilds.find((guild) => guild.id === activeGuildId) ?? null,
    [guilds, activeGuildId]
  );

  // Read-only when the active guild is a grant that isn't read-write, OR when
  // the guild's content is frozen server-side (read_only lifecycle status —
  // writes already die at the database role level; the UI must match).
  const activeGuildReadOnly =
    (activeGuild?.accessType === "grant" && activeGuild?.grantAccessLevel !== "read_write") ||
    Boolean(activeGuild?.content_read_only);

  const value: GuildContextValue = {
    guilds,
    activeGuildId,
    activeGuild,
    activeGuildReadOnly,
    loading,
    error,
    refreshGuilds,
    switchGuild,
    syncGuildFromUrl,
    createGuild,
    updateGuildInState,
    reorderGuilds,
    canCreateGuilds,
  };

  return <GuildContext.Provider value={value}>{children}</GuildContext.Provider>;
};

export const useGuilds = () => {
  const context = useContext(GuildContext);
  if (!context) {
    throw new Error("useGuilds must be used within a GuildProvider");
  }
  return context;
};
