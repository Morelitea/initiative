import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";

import { invalidateNotifications } from "@/api/query-keys";
import { useAuth } from "@/hooks/useAuth";
import { buildApiWsUrl } from "@/lib/wsUrl";

// Message type for authentication (must match the backend's MSG_AUTH).
const MSG_AUTH = 5;
// "Somebody just did something here" (the backend's MSG_ACTIVE). One byte, no
// payload: the socket already knows whose it is.
const MSG_ACTIVE = 6;

// How often that byte may go out, however busy the keyboard is. The server
// only needs to know the person was around within its idle window, so once a
// minute answers that with a frame nobody would notice.
const ACTIVITY_INTERVAL_MS = 60_000;

// What counts as a sign of someone. Pointer, key and scroll cover being at the
// machine; a tab coming back to the front covers returning to it.
const ACTIVITY_EVENTS = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

const RECONNECT_DELAY_MS = 2000;
const MAX_RECONNECT_DELAY_MS = 30_000;

// A frame is the only prompt to re-read the account, so a re-read that fails
// has to keep trying: there is no poll behind it any more, and the next frame
// may never come for this account. What is bounded is the *rate*, not the
// number of attempts — giving up would leave the tab holding an account it
// already knows is wrong, which is the thing this whole channel exists to
// prevent. Backs off to a slow beat and stays there until one lands.
const ACCOUNT_RETRY_DELAYS_MS = [2000, 8000, 30_000, 60_000] as const;
const ACCOUNT_RETRY_MAX_DELAY_MS = 300_000;
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

const sendActivityMessage = (websocket: WebSocket) => {
  if (websocket.readyState !== WebSocket.OPEN) {
    return;
  }
  websocket.send(new Uint8Array([MSG_ACTIVE]));
};

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
 * It carries one thing the other way: a throttled byte saying its person is at
 * the keyboard. That is what keeps them from reading as idle — and going quiet
 * is the whole signal, so a tab left open needs to send nothing for the server
 * to work out that nobody is at it.
 *
 * Mount once, at the authenticated app shell.
 */
export const useNotificationStream = () => {
  const { token, user, refreshUser } = useAuth();
  const websocketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const authFailureCountRef = useRef(0);
  // Held in a ref so a new `refreshUser` identity does not tear the socket
  // down and rebuild it: the handler wants the current one, not the one that
  // existed when we connected.
  const refreshUserRef = useRef(refreshUser);
  refreshUserRef.current = refreshUser;
  const accountRetryTimerRef = useRef<number | null>(null);

  // Re-read the account, and keep trying for a short while if it does not
  // land. One in-flight attempt at a time: a second frame arriving mid-retry
  // restarts the sequence rather than racing it.
  const refreshAccount = useCallback((attempt = 0) => {
    if (accountRetryTimerRef.current !== null) {
      window.clearTimeout(accountRetryTimerRef.current);
      accountRetryTimerRef.current = null;
    }
    // Wrapped rather than chained straight off the call: the guard covers a
    // missing function, not a return that is not a promise.
    void Promise.resolve(refreshUserRef.current?.()).catch(() => {
      // Past the end of the ramp it stays at the slowest beat rather than
      // stopping: the account is known to be out of date, and nothing else is
      // coming to correct it.
      const delay = ACCOUNT_RETRY_DELAYS_MS[attempt] ?? ACCOUNT_RETRY_MAX_DELAY_MS;
      accountRetryTimerRef.current = window.setTimeout(() => {
        accountRetryTimerRef.current = null;
        refreshAccount(attempt + 1);
      }, delay);
    });
  }, []);

  useEffect(
    () => () => {
      if (accountRetryTimerRef.current !== null) {
        window.clearTimeout(accountRetryTimerRef.current);
        accountRetryTimerRef.current = null;
      }
    },
    []
  );

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
        // The socket was down for some interval — anything that happened in it
        // was never signalled, so catch up once on the way back up. Both
        // channels, since either could have moved while we were away.
        void invalidateNotifications();
        refreshAccount();
      };

      websocket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as { resource?: string };
          // Two channels over one socket. A frame carries nothing but which
          // one it is; what it means is a refetch, and the refetch is where
          // anything is actually decided.
          if (payload.resource === "notification") {
            void invalidateNotifications();
          } else if (payload.resource === "account") {
            refreshAccount();
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

    // Throttled at the source rather than on a timer: no frame goes out for a
    // tab nobody is touching, which is exactly the state being reported.
    let lastReported = 0;
    const reportActivity = () => {
      const now = Date.now();
      if (now - lastReported < ACTIVITY_INTERVAL_MS) {
        return;
      }
      lastReported = now;
      if (websocketRef.current) {
        sendActivityMessage(websocketRef.current);
      }
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        // Coming back to the tab is being back, whenever the last click was.
        lastReported = 0;
        reportActivity();
      }
    };
    for (const name of ACTIVITY_EVENTS) {
      window.addEventListener(name, reportActivity, { passive: true });
    }
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      isActive = false;
      for (const name of ACTIVITY_EVENTS) {
        window.removeEventListener(name, reportActivity);
      }
      document.removeEventListener("visibilitychange", onVisibilityChange);
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
  }, [token, user, refreshAccount]);
};
