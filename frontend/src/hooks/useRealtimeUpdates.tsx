import { useParams } from "@tanstack/react-router";
import { useEffect, useRef } from "react";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q, type Spec } from "@/api/query-keys";
import { TOOLS, toolPlural } from "@/lib/tools";
import { buildGuildWsUrl } from "@/lib/wsUrl";

import { useAuth } from "./useAuth";

// Message type for authentication (must match backend)
const MSG_AUTH = 5;

// The server says something every 30s even with no news (its
// HEARTBEAT_SECONDS), so silence past a couple of those is the socket having
// stopped carrying rather than the guild being quiet. A dropped connection
// does not always close: a suspended laptop, a network that goes away
// mid-flight and a NAT timeout all leave one reporting itself open and
// delivering nothing.
const SERVER_SILENCE_LIMIT_MS = 90_000;
// How often that is checked. Cheap: a comparison against a timestamp.
const SILENCE_CHECK_INTERVAL_MS = 15_000;

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

/**
 * Send authentication message over WebSocket.
 * Must be sent immediately after connection opens.
 *
 * The socket is scoped server-side to the guild in the route path (the backend
 * only streams that guild's events), so the payload carries the token only.
 * The hook reconnects on guild switch, so the subscription always tracks the
 * guild this tab is looking at.
 *
 * A reconnect also says how long this tab was without a socket, which is what
 * the server needs to answer whether anything happened in that time. A first
 * connect says nothing: the route that just mounted fetched its own data.
 */
const sendAuthMessage = (
  websocket: WebSocket,
  token: string | null,
  awaySeconds: number | null
) => {
  const payload = JSON.stringify(
    awaySeconds === null ? { token } : { token, away_seconds: awaySeconds }
  );
  const payloadBytes = new TextEncoder().encode(payload);
  const message = new Uint8Array(1 + payloadBytes.length);
  message[0] = MSG_AUTH;
  message.set(payloadBytes, 1);
  websocket.send(message);
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
  const websocketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const authFailureCountRef = useRef<number>(0);

  useEffect(() => {
    // The socket is scoped to a single guild — in personal mode there's
    // nothing to subscribe to, and the backend would reject the auth payload.
    if (userId === null || routeGuildId === null) {
      if (websocketRef.current) {
        websocketRef.current.close();
        websocketRef.current = null;
      }
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      authFailureCountRef.current = 0;
      return;
    }
    // routeGuildId is non-null past the guard; capture for the /c/{guildId}
    // websocket path used in the connect() closure below.
    const guildId = routeGuildId;

    let isActive = true;

    // Effect-scoped, so unmount and guild-switch clear the timer with the
    // socket rather than invalidating for a guild this tab has left.
    let pending: RealtimeChange[] = [];
    let frameTimer: number | null = null;
    // The last moment this tab had a socket that was carrying. Any frame is
    // proof of that, so a beat counts; nothing else does.
    let lastFrameAt = Date.now();
    // Set when a socket closes, so the next one can say how long the tab went
    // without one. Null until then — a first connect asks for nothing.
    let carriedUntil: number | null = null;

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

    const scheduleReconnect = (delayMs = 2000) => {
      if (!isActive || reconnectTimerRef.current !== null) {
        return;
      }
      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null;
        connect();
      }, delayMs);
    };

    const connect = () => {
      if (!isActive) {
        return;
      }
      const wsUrl = buildWebsocketUrl(guildId);
      if (!wsUrl) {
        scheduleReconnect();
        return;
      }
      const websocket = new WebSocket(wsUrl);
      websocket.binaryType = "arraybuffer";
      websocketRef.current = websocket;

      websocket.onopen = () => {
        // Send auth message immediately after connection (token not in URL for
        // security). The guild id scopes the stream to the active guild.
        sendAuthMessage(
          websocket,
          token,
          carriedUntil === null ? null : (Date.now() - carriedUntil) / 1000
        );
        // Reset failure count on successful connection
        authFailureCountRef.current = 0;
        lastFrameAt = Date.now();
      };

      websocket.onmessage = (event) => {
        // Any frame is proof the socket carries, whatever it says. A beat says
        // only that, and needs nothing below.
        lastFrameAt = Date.now();
        try {
          // A content-free invalidation bus: every frame is one transaction's
          // worth of {resource, parents, action}, never a serialized model. We
          // read the identifiers and refetch through the normal (RLS + DAC
          // gated) REST path — that refetch is the authorization gate.
          const payload = JSON.parse(event.data) as {
            changes?: RealtimeChange[];
            more?: boolean;
          };
          if (payload.more) {
            // A write too large to name row by row — an import, a purge. The
            // frame says so instead of carrying thousands of ids, and the
            // answer is to read the guild again.
            void invalidate(q.guildContent());
            return;
          }
          const changes = payload.changes ?? [];
          if (changes.length) {
            enqueue(changes);
          }
        } catch {
          // ignore malformed messages
        }
      };

      websocket.onerror = () => {
        websocket.close();
      };

      websocket.onclose = (event) => {
        if (websocketRef.current === websocket) {
          websocketRef.current = null;
        }
        // Dated from the last frame rather than from now: a socket that went
        // quiet stopped carrying when it went quiet, not when we noticed.
        carriedUntil = lastFrameAt;
        // WS_1008_POLICY_VIOLATION (1008) indicates auth failure (403)
        if (event.code === 1008) {
          authFailureCountRef.current += 1;
          // After 3 consecutive auth failures, stop trying and log out
          if (authFailureCountRef.current >= 3) {
            console.warn("WebSocket auth failed repeatedly, logging out");
            logout();
            return;
          }
          // Use exponential backoff for auth failures
          scheduleReconnect(Math.min(30000, 2000 * 2 ** authFailureCountRef.current));
          return;
        }
        scheduleReconnect();
      };
    };

    connect();

    // A socket that has gone quiet past the server's beat is closed rather than
    // trusted. Closing is what starts the reconnect, which is what asks the
    // server whether anything moved in the meantime.
    const silenceCheck = window.setInterval(() => {
      const socket = websocketRef.current;
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        return;
      }
      if (Date.now() - lastFrameAt > SERVER_SILENCE_LIMIT_MS) {
        socket.close();
      }
    }, SILENCE_CHECK_INTERVAL_MS);

    return () => {
      isActive = false;
      window.clearInterval(silenceCheck);
      if (frameTimer !== null) {
        window.clearTimeout(frameTimer);
        frameTimer = null;
      }
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (websocketRef.current) {
        websocketRef.current.close();
        websocketRef.current = null;
      }
    };
  }, [token, userId, routeGuildId, logout]);
};
