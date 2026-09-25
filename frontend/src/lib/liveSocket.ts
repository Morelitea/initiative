/**
 * One authenticated WebSocket, kept open.
 *
 * Every JSON push channel — the per-guild events bus, the personal
 * notification stream and a queue's or counter group's change signal — needs
 * the same connection underneath: authenticate in the first frame, reconnect
 * with jittered backoff, stop for good once the credential has been rejected
 * repeatedly, and notice a socket that has stopped carrying without ever
 * closing. This is the one copy. (The collaboration socket speaks Yjs frames
 * and keeps its own connection, with the same backoff.)
 *
 * What differs between the two channels sits above it — which address, what
 * else rides in the auth frame, and what a frame means — and that is the whole
 * of the options.
 */

import { reconnectDelay } from "@/lib/reconnectBackoff";

// Must match the backend's MSG_AUTH. The token rides in the first frame rather
// than the URL, so it never lands in a proxy or server access log.
const MSG_AUTH = 5;

const RECONNECT_DELAY_MS = 2000;
const MAX_RECONNECT_DELAY_MS = 30_000;

// Three consecutive policy-violation closes means the credential is no good,
// not that the network blinked.
const MAX_AUTH_FAILURES = 3;

// The server says something every 30s even with no news (its
// HEARTBEAT_SECONDS), so silence past a couple of those is the socket having
// stopped carrying rather than nothing having happened. A dropped connection
// does not always close: a suspended laptop, a network that goes away
// mid-flight and a NAT timeout all leave one reporting itself open and
// delivering nothing.
const SERVER_SILENCE_LIMIT_MS = 90_000;
// How often that is checked. Cheap: a comparison against a timestamp.
const SILENCE_CHECK_INTERVAL_MS = 15_000;

export type LiveSocket = {
  /** Send on the socket if one is open; a no-op otherwise. */
  send: (data: Uint8Array<ArrayBuffer>) => void;
  /** Stop reconnecting and close. */
  close: () => void;
};

export type LiveSocketOptions = {
  url: string;
  /**
   * The first frame's payload.
   *
   * `awaySeconds` is how long this tab went without a socket that was
   * carrying, or null if it has never had one — which is what lets a server
   * answer whether anything moved in the meantime. A first connect asks for
   * nothing, having fetched as it mounted.
   */
  auth: (awaySeconds: number | null) => Record<string, unknown>;
  /** One parsed frame. Malformed frames never reach it. */
  onFrame: (payload: unknown) => void;
  /** True when a socket opens, false when one closes. */
  onStatus?: (connected: boolean) => void;
  /** The credential was rejected repeatedly; nothing further is attempted. */
  onAuthRejected?: () => void;
};

export const openLiveSocket = ({
  url,
  auth,
  onFrame,
  onStatus,
  onAuthRejected,
}: LiveSocketOptions): LiveSocket => {
  let socket: WebSocket | null = null;
  let reconnectTimer: number | null = null;
  let active = true;
  let authFailures = 0;
  // Attempts since a socket last carried a frame: what widens the backoff.
  let attempts = 0;
  // The last frame this socket saw, which is what silence is measured against.
  // Reset on open so a fresh socket is not closed for its predecessor's quiet.
  let lastFrameAt = Date.now();
  // The last frame received on ANY socket here, which is the last proof this
  // tab was being carried. Only a frame moves it: an attempt that opens and
  // dies before hearing anything has proved nothing, and must not shorten the
  // gap the next attempt reports.
  let carriedUntil: number | null = null;

  const scheduleReconnect = () => {
    if (!active || reconnectTimer !== null) {
      return;
    }
    const delayMs = reconnectDelay(attempts, RECONNECT_DELAY_MS, MAX_RECONNECT_DELAY_MS);
    attempts += 1;
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delayMs);
  };

  const connect = () => {
    if (!active) {
      return;
    }
    let next: WebSocket;
    try {
      next = new WebSocket(url);
    } catch {
      scheduleReconnect();
      return;
    }
    next.binaryType = "arraybuffer";
    socket = next;

    next.onopen = () => {
      const away = carriedUntil === null ? null : (Date.now() - carriedUntil) / 1000;
      const payload = new TextEncoder().encode(JSON.stringify(auth(away)));
      const frame = new Uint8Array(1 + payload.length);
      frame[0] = MSG_AUTH;
      frame.set(payload, 1);
      next.send(frame);
      lastFrameAt = Date.now();
      onStatus?.(true);
    };

    next.onmessage = (event) => {
      // Any frame is proof the socket carries, whatever it says — and the
      // first of them is proof the credential was accepted, which is what
      // clears the count. Opening is not: the auth frame is sent after the
      // socket opens and answered after that, so opening says nothing yet.
      authFailures = 0;
      attempts = 0;
      lastFrameAt = Date.now();
      carriedUntil = lastFrameAt;
      let payload: unknown;
      try {
        payload = JSON.parse(event.data as string);
      } catch {
        return;
      }
      onFrame(payload);
    };

    next.onerror = () => {
      next.close();
    };

    next.onclose = (event) => {
      if (socket === next) {
        socket = null;
      }
      onStatus?.(false);
      // WS_1008_POLICY_VIOLATION — the credential was rejected.
      if (event.code === 1008) {
        authFailures += 1;
        if (authFailures >= MAX_AUTH_FAILURES) {
          onAuthRejected?.();
          return;
        }
      }
      scheduleReconnect();
    };
  };

  connect();

  // A socket that has gone quiet past the server's beat is closed rather than
  // trusted. Closing is what starts the reconnect, which is what asks the
  // server whether anything moved in the meantime.
  const silenceCheck = window.setInterval(() => {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }
    if (Date.now() - lastFrameAt > SERVER_SILENCE_LIMIT_MS) {
      socket.close();
    }
  }, SILENCE_CHECK_INTERVAL_MS);

  return {
    send: (data) => {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(data);
      }
    },
    close: () => {
      active = false;
      window.clearInterval(silenceCheck);
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (socket) {
        socket.close();
        socket = null;
      }
    },
  };
};
