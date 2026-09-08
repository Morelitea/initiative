import { useParams } from "@tanstack/react-router";
import { useEffect, useRef } from "react";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import {
  invalidateAllTasks,
  invalidateProject,
  invalidateProjectActivity,
  invalidateRecentComments,
  invalidateTask,
  invalidateTaskComments,
  invalidateTool,
  invalidateToolComments,
} from "@/api/query-keys";
import { TOOLS, toolForResourceName, toolIdParam } from "@/lib/tools";
import { buildGuildWsUrl } from "@/lib/wsUrl";

import { useAuth } from "./useAuth";

// Message type for authentication (must match backend)
const MSG_AUTH = 5;

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
 * The socket is scoped server-side to the user's server-held guild context
 * (the backend only streams that guild's events), so the payload carries the
 * token only. The hook reconnects on guild switch — after the context PUT —
 * so the subscription always tracks the active guild.
 */
const sendAuthMessage = (websocket: WebSocket, token: string | null) => {
  const payload = JSON.stringify({ token });
  const payloadBytes = new TextEncoder().encode(payload);
  const message = new Uint8Array(1 + payloadBytes.length);
  message[0] = MSG_AUTH;
  message.set(payloadBytes, 1);
  websocket.send(message);
};

// Bursts of task events (an import, another user's bulk operation) coalesce
// into one refetch per window instead of one per event — the signal is
// content-free, so collapsing duplicates loses nothing. The debounce state
// lives inside the socket effect so it dies with the socket.
const TASK_EVENT_DEBOUNCE_MS = 300;

/** One id off an event envelope, or null when the frame does not carry it. */
const eventId = (data: Record<string, unknown> | undefined, key: string): number | null => {
  const raw = data?.[key];
  if (raw === null || raw === undefined) return null;
  const value = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(value) ? value : null;
};

/**
 * A tool entity moved — its own row and its tool's lists are now stale.
 *
 * Derived from the registry rather than a case per tool: the bus names a
 * resource by the tool's own enum value, and `invalidateTool` is a
 * `Record<Tool, …>`, so a new tool is live the day it ships.
 */
export const handleToolEvent = (tool: Tool, data?: Record<string, unknown>) => {
  const id = eventId(data, toolIdParam(tool));
  if (id === null) return;
  invalidateTool(tool, id);
};

/**
 * A comment (or a reaction on one) landed somewhere in this initiative.
 *
 * A comment hangs off exactly one parent — a task, or any tool entity — and the
 * envelope carries that parent's `{parent}_id`, mirroring the backend's
 * `_COMMENT_PARENTS`. Walking the tool registry means the ninth tool's threads
 * are live without touching this function; hard-coding the parents is what left
 * every tool but tasks waiting for the next refetch.
 *
 * Both the thread AND the parent are refreshed: the surfaces around a thread
 * (a post card, a document card) show a comment count that has just moved.
 */
export const handleCommentEvent = (data?: Record<string, unknown>) => {
  // The guild's recent-activity list is a comment feed of its own.
  void invalidateRecentComments();
  // A project's activity feed lists comments from its tasks as well as its own,
  // which is why the envelope names the project of a task comment too.
  const projectId = eventId(data, "project_id");
  if (projectId !== null) {
    void invalidateProjectActivity(projectId);
  }
  const taskId = eventId(data, "task_id");
  if (taskId !== null) {
    void invalidateTaskComments(taskId);
    // The task's own comment count. Its board and list cards ride on the
    // debounced task-event path, which a comment is not.
    void invalidateTask(taskId);
    // That `project_id` was the task's project, not a second parent: a comment
    // has exactly one.
    return;
  }
  for (const tool of TOOLS) {
    const id = eventId(data, toolIdParam(tool));
    if (id === null) continue;
    void invalidateToolComments(tool, id);
    handleToolEvent(tool, data);
  }
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

    // Effect-scoped debounce: a burst of task events costs one refetch per
    // window, and unmount/guild-switch clears the timer with the socket.
    const pendingTaskProjectIds = new Set<number>();
    let taskEventTimer: number | null = null;

    const handleTaskEvent = (data?: Record<string, unknown>) => {
      const projectId = data?.project_id;
      if (typeof projectId === "number") {
        pendingTaskProjectIds.add(projectId);
      }
      if (taskEventTimer !== null) {
        return;
      }
      taskEventTimer = window.setTimeout(() => {
        taskEventTimer = null;
        const projectIds = [...pendingTaskProjectIds];
        pendingTaskProjectIds.clear();
        void invalidateAllTasks();
        for (const id of projectIds) {
          void invalidateProject(id);
        }
      }, TASK_EVENT_DEBOUNCE_MS);
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
        sendAuthMessage(websocket, token);
        // Reset failure count on successful connection
        authFailureCountRef.current = 0;
      };

      websocket.onmessage = (event) => {
        try {
          // The realtime stream is a content-free invalidation bus: each message
          // is an id envelope ({resource, action, ids}), never a serialized
          // model. We read only the ids and refetch through the normal
          // (RLS + DAC gated) REST path — that refetch is the authorization gate.
          const payload = JSON.parse(event.data) as {
            resource?: string;
            ids?: Record<string, unknown>;
          };
          switch (payload.resource) {
            case "task":
              handleTaskEvent(payload.ids);
              break;
            case "comment":
              handleCommentEvent(payload.ids);
              break;
            default: {
              // Every other resource on the bus is a tool, named by its own
              // enum value — projects, and posts whose reactions just moved.
              const tool = toolForResourceName(payload.resource);
              if (tool) {
                handleToolEvent(tool, payload.ids);
              }
              break;
            }
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

    return () => {
      isActive = false;
      if (taskEventTimer !== null) {
        window.clearTimeout(taskEventTimer);
        taskEventTimer = null;
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
