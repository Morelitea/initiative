import { useEffect, useRef } from "react";

import { API_BASE_URL } from "@/api/client";
import {
  invalidateAllDocuments,
  invalidateAllProjects,
  invalidateAllTasks,
  invalidateDocument,
  invalidateDocumentComments,
  invalidateProject,
  invalidateProjectActivity,
  invalidateTaskComments,
} from "@/api/query-keys";

import { useAuth } from "./useAuth";
import { useGuilds } from "./useGuilds";

// Message type for authentication (must match backend)
const MSG_AUTH = 5;

const buildWebsocketUrl = (guildId: number) => {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const base =
      API_BASE_URL.startsWith("http://") || API_BASE_URL.startsWith("https://")
        ? new URL(API_BASE_URL)
        : new URL(API_BASE_URL, window.location.origin);

    const normalizedPath = base.pathname.endsWith("/")
      ? base.pathname.slice(0, -1)
      : base.pathname || "/api/v1";

    base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
    base.pathname = `${normalizedPath}/g/${guildId}/events/updates`;
    base.search = "";
    base.hash = "";
    // Token is sent via MSG_AUTH message, not URL params (for security)
    return base.toString();
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

const handleTaskEvent = (data?: Record<string, unknown>) => {
  void invalidateAllTasks();
  const projectId = data?.project_id;
  if (typeof projectId === "number") {
    void invalidateProject(projectId);
  }
};

const handleProjectEvent = () => {
  void invalidateAllProjects();
};

const handleCommentEvent = (data?: Record<string, unknown>) => {
  const taskId = typeof data?.task_id === "number" ? data.task_id : Number(data?.task_id);
  if (Number.isFinite(taskId)) {
    void invalidateTaskComments(taskId);
  }
  const documentId =
    typeof data?.document_id === "number" ? data.document_id : Number(data?.document_id);
  if (Number.isFinite(documentId)) {
    void invalidateDocumentComments(documentId);
    void invalidateDocument(documentId);
  }
  void invalidateAllDocuments();
  const projectId =
    typeof data?.project_id === "number" ? data.project_id : Number(data?.project_id);
  if (Number.isFinite(projectId)) {
    void invalidateProjectActivity(projectId);
  }
};

export const useRealtimeUpdates = () => {
  const { token, user, logout } = useAuth();
  // Key the socket off the SERVER-held context, not the local "last guild"
  // preference: the backend scopes the stream to users.active_guild_id and
  // policy-closes the socket when it's NULL (personal mode). Connecting off
  // the local preference while in personal mode would auth-fail repeatedly
  // and eventually force a logout.
  const { serverGuildId } = useGuilds();
  const websocketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const authFailureCountRef = useRef<number>(0);

  useEffect(() => {
    // The socket is scoped to a single guild — in personal mode there's
    // nothing to subscribe to, and the backend would reject the auth payload.
    if (!user || serverGuildId === null) {
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
    // serverGuildId is non-null past the guard; capture as a number for the
    // /g/{guildId} websocket path used in the connect() closure below.
    const guildId = serverGuildId;

    let isActive = true;

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
          const payload = JSON.parse(event.data) as {
            resource?: string;
            data?: Record<string, unknown>;
          };
          switch (payload.resource) {
            case "task":
              handleTaskEvent(payload.data);
              break;
            case "project":
              handleProjectEvent();
              break;
            case "comment":
              handleCommentEvent(payload.data);
              break;
            default:
              break;
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
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (websocketRef.current) {
        websocketRef.current.close();
        websocketRef.current = null;
      }
    };
  }, [token, user, serverGuildId, logout]);
};
