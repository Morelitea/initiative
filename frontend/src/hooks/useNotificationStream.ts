import { useEffect, useRef, useSyncExternalStore } from "react";

import { invalidateNotifications } from "@/api/query-keys";
import { useAuth } from "@/hooks/useAuth";
import { buildApiWsUrl } from "@/lib/wsUrl";

// Message type for authentication (must match the backend's MSG_AUTH).
const MSG_AUTH = 5;

const RECONNECT_DELAY_MS = 2000;
const MAX_RECONNECT_DELAY_MS = 30_000;
// Three consecutive policy-violation closes means the credential is no good,
// not that the network blinked — same rule as the guild events socket.
const MAX_AUTH_FAILURES = 3;

// ── Connection state, shared with whoever renders the bell ──────────────────
// The socket is mounted once at the app shell, but the component that decides
// whether to poll is the bell, several levels down. A module-level store read
// through `useSyncExternalStore` keeps that one boolean available to both
// without threading a provider through the tree.

let connected = false;
const listeners = new Set<() => void>();

const setConnected = (next: boolean) => {
  if (connected === next) {
    return;
  }
  connected = next;
  for (const listener of listeners) {
    listener();
  }
};

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

/**
 * Whether the notification push channel is currently open.
 *
 * Consumers use this to decide whether they still need to poll: a socket that
 * never connects (a proxy that drops upgrades, a browser offline) must not
 * mean notifications stop arriving altogether.
 */
export const useNotificationStreamConnected = (): boolean =>
  useSyncExternalStore(
    subscribe,
    () => connected,
    () => false
  );

const sendAuthMessage = (websocket: WebSocket, token: string | null) => {
  const payload = JSON.stringify({ token });
  const payloadBytes = new TextEncoder().encode(payload);
  const message = new Uint8Array(1 + payloadBytes.length);
  message[0] = MSG_AUTH;
  message.set(payloadBytes, 1);
  websocket.send(message);
};

/**
 * Subscribe to the signed-in user's notification channel.
 *
 * The inbox is personal and cross-guild, so this socket is addressed by
 * nothing but the credential — unlike `useRealtimeUpdates`, whose socket is
 * per-guild and only exists inside a `/g/{guildId}` route. It therefore stays
 * open on personal routes too, which is exactly where the bell still lives.
 *
 * Every frame is a content-free "your inbox changed"; the response is to
 * invalidate the notification queries and let React Query refetch through the
 * normal REST path, which is the authorization gate.
 *
 * Mount once, at the authenticated app shell.
 */
export const useNotificationStream = () => {
  const { token, user } = useAuth();
  const websocketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const authFailureCountRef = useRef(0);

  useEffect(() => {
    if (!user) {
      return;
    }

    let isActive = true;

    const scheduleReconnect = (delayMs = RECONNECT_DELAY_MS) => {
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
      let websocket: WebSocket;
      try {
        websocket = new WebSocket(buildApiWsUrl("notifications/stream"));
      } catch {
        scheduleReconnect();
        return;
      }
      websocket.binaryType = "arraybuffer";
      websocketRef.current = websocket;

      websocket.onopen = () => {
        // The token rides in the first frame rather than the URL, so it never
        // lands in a proxy or server access log.
        sendAuthMessage(websocket, token);
        authFailureCountRef.current = 0;
        setConnected(true);
        // The socket was down for some interval — anything that arrived in it
        // was never signalled, so catch up once on the way back up.
        void invalidateNotifications();
      };

      websocket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as { resource?: string };
          if (payload.resource === "notification") {
            void invalidateNotifications();
          }
        } catch {
          // ignore malformed frames
        }
      };

      websocket.onerror = () => {
        websocket.close();
      };

      websocket.onclose = (event) => {
        if (websocketRef.current === websocket) {
          websocketRef.current = null;
        }
        setConnected(false);
        // WS_1008_POLICY_VIOLATION — the credential was rejected. Back off
        // hard and give up rather than hammering the endpoint; the bell falls
        // back to polling, and the guild events socket owns logging out.
        if (event.code === 1008) {
          authFailureCountRef.current += 1;
          if (authFailureCountRef.current >= MAX_AUTH_FAILURES) {
            return;
          }
          scheduleReconnect(
            Math.min(MAX_RECONNECT_DELAY_MS, RECONNECT_DELAY_MS * 2 ** authFailureCountRef.current)
          );
          return;
        }
        scheduleReconnect();
      };
    };

    connect();

    return () => {
      isActive = false;
      setConnected(false);
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (websocketRef.current) {
        websocketRef.current.close();
        websocketRef.current = null;
      }
    };
  }, [token, user]);
};
