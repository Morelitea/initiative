import { useParams } from "@tanstack/react-router";
import { useEffect } from "react";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q, type Spec } from "@/api/query-keys";
import { openLiveSocket } from "@/lib/liveSocket";
import { TOOLS, toolPlural } from "@/lib/tools";
import { buildGuildWsUrl } from "@/lib/wsUrl";

import { useAuth } from "./useAuth";

const buildWebsocketUrl = (guildId: number) => {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    // Token is sent via MSG_AUTH message, not URL params
    return buildGuildWsUrl(guildId, "events/updates");
  } catch {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    return `${protocol}://${window.location.host}/api/v1/g/${guildId}/events/updates`;
  }
};

/** One thing the bus can name: what changed, or something it sits inside. */
export type ResourceRef = { type: string; id: number };

/** One change off the wire. Identifiers only — never a serialized model. */
export type RealtimeChange = {
  resource?: ResourceRef;
  parents?: ResourceRef[];
  action?: string;
};

/**
 * A burst of frames costs one round of invalidation rather than one per frame.
 * The server already batches a transaction into a single frame, so this only
 * has to cover separate writes landing together — somebody dragging cards, an
 * import committing in chunks.
 */
const FRAME_DEBOUNCE_MS = 250;

/**
 * What a change to one kind of resource makes stale — as a description, not an
 * action.
 *
 * Tools come from the registry, so a new tool's events are live the day it
 * ships. The rest are the things the bus can name that are not a tool of their
 * own. A type nothing here claims is ignored on purpose: its parents carry the
 * surfaces that matter, and a queue item is refreshed by refreshing its queue.
 */
const RESOURCE_SPECS: Record<string, (id: number) => Spec[]> = {
  ...Object.fromEntries(
    TOOLS.map((tool) => [toolPlural(tool), (id: number) => [q.tool(tool, id)]])
  ),
  // A project's activity feed lists its own comments and its tasks', so it is
  // stale for anything that happens anywhere inside the project. Declared after
  // the registry spread, which it extends rather than replaces.
  projects: (id) => [q.tool(Tool.project, id), q.projectActivity(id)],
  tasks: (id) => [q.task(id), q.allTasks()],
  subtasks: (id) => [q.subtask(id)],
  // The guild's recent-activity list is a comment feed of its own. Which thread
  // moved is a question about the parent, below.
  comments: () => [q.recentComments()],
  calendar_events: (id) => [q.calendarEvent(id), q.allCalendarEvents()],
  // An initiative's roster, its roles and what those roles permit all report
  // against the initiative itself — a membership row and a role row have no
  // route of their own — so "the initiative changed" has to name all three.
  initiatives: (id) => [
    q.initiative(id),
    q.allInitiatives(),
    q.initiativeMembers(id),
    q.initiativeRoles(id),
    q.myPermissions(id),
  ],
  tags: (id) => [q.tag(id), q.allTags()],
  // An install belongs to no initiative, so it arrives guild-wide with no
  // parent to carry it — this is the only thing that refreshes the sidebar's
  // app list and the settings dialog for another admin's install, rename or
  // configuration. Takes no id: the reads are keyed by guild, not by install.
  apps: () => [q.apps()],
  property_definitions: () => [q.allProperties()],
};

/**
 * What a change to a child makes stale ON the parent it hangs off.
 *
 * The one thing naming the parent does not cover: these queries are keyed by
 * the parent rather than by the child, so nothing about the child's own id
 * reaches them.
 */
const PARENT_SPECS: Record<string, (parent: ResourceRef) => Spec[]> = {
  comments: (parent) => [q.commentsOnResource(parent.type, parent.id)],
  subtasks: (parent) => (parent.type === "tasks" ? [q.taskSubtasks(parent.id)] : []),
};

const isRef = (value: unknown): value is ResourceRef => {
  const ref = value as ResourceRef | undefined;
  return typeof ref?.type === "string" && Number.isFinite(ref?.id);
};

const refKey = (ref: ResourceRef) => `${ref.type}:${ref.id}`;

/**
 * Refresh everything a batch of changes made stale, in one pass over the cache.
 *
 * Two passes over the same batch collect the description: the resources named
 * (the change itself, and every resource it sits inside), then the parent-keyed
 * queries only a child can point at. Nothing is matched until both are in hand,
 * so three hundred comments on one task cost the same single walk as one — and
 * the repeats among them collapse when the specs merge.
 */
export const applyChanges = (changes: readonly RealtimeChange[]) => {
  const refs = new Map<string, ResourceRef>();
  const effects = new Map<string, [string, ResourceRef]>();

  for (const change of changes) {
    const resource = change.resource;
    const parents = (change.parents ?? []).filter(isRef);
    if (isRef(resource)) {
      refs.set(refKey(resource), resource);
      if (parents[0]) {
        effects.set(`${resource.type}|${refKey(parents[0])}`, [resource.type, parents[0]]);
      }
    }
    for (const parent of parents) {
      refs.set(refKey(parent), parent);
    }
  }

  const specs: Spec[] = [];
  for (const ref of refs.values()) {
    specs.push(...(RESOURCE_SPECS[ref.type]?.(ref.id) ?? []));
  }
  for (const [childType, parent] of effects.values()) {
    specs.push(...(PARENT_SPECS[childType]?.(parent) ?? []));
  }
  if (specs.length > 0) void invalidate(...specs);
};

export const useRealtimeUpdates = () => {
  const { token, user, logout } = useAuth();
  // Keyed on the id, not the object: an account re-read replaces the object
  // without changing who is signed in, and rebuilding the socket for that would
  // drop every subscription over a no-op.
  const userId = user?.id ?? null;
  // Key the socket off THIS tab's URL guild (the /c/{guildId} route param), so
  // each tab streams its own guild. On personal routes (/, /me/*) there's no
  // param → null → no socket. The backend authorizes the socket from the same
  // path segment, so the URL is the single source of truth.
  const params = useParams({ strict: false }) as { guildId?: string };
  const routeGuildId = params.guildId ? Number(params.guildId) : null;

  useEffect(() => {
    // The socket is scoped to a single guild — in personal mode there's
    // nothing to subscribe to, and the backend would reject the auth payload.
    if (userId === null || routeGuildId === null) {
      return;
    }
    const wsUrl = buildWebsocketUrl(routeGuildId);
    if (!wsUrl) {
      return;
    }

    // Effect-scoped, so unmount and guild-switch clear the timer with the
    // socket rather than invalidating for a guild this tab has left.
    let pending: RealtimeChange[] = [];
    let frameTimer: number | null = null;

    const enqueue = (changes: RealtimeChange[]) => {
      pending.push(...changes);
      if (frameTimer !== null) {
        return;
      }
      frameTimer = window.setTimeout(() => {
        frameTimer = null;
        const batch = pending;
        pending = [];
        applyChanges(batch);
      }, FRAME_DEBOUNCE_MS);
    };

    const connection = openLiveSocket({
      url: wsUrl,
      // The guild is in the address, so the frame carries the credential and
      // the gap this tab is asking to have answered.
      auth: (awaySeconds) =>
        awaySeconds === null ? { token } : { token, away_seconds: awaySeconds },
      onFrame: (payload) => {
        // A content-free invalidation bus: every frame is one transaction's
        // worth of {resource, parents, action}, never a serialized model. We
        // read the identifiers and refetch through the normal (RLS + DAC
        // gated) REST path — that refetch is the authorization gate.
        const frame = payload as { changes?: RealtimeChange[]; more?: boolean };
        if (frame.more) {
          // A write too large to name row by row — an import, a purge — or a
          // gap this socket was away for. Either way the frame says so instead
          // of carrying ids, and the answer is to read the guild again.
          void invalidate(q.guildContent());
          return;
        }
        const changes = frame.changes ?? [];
        if (changes.length) {
          enqueue(changes);
        }
      },
      onAuthRejected: () => {
        console.warn("WebSocket auth failed repeatedly, logging out");
        logout();
      },
    });

    return () => {
      connection.close();
      if (frameTimer !== null) {
        window.clearTimeout(frameTimer);
        frameTimer = null;
      }
    };
  }, [token, userId, routeGuildId, logout]);
};
