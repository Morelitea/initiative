/**
 * Yjs collaboration with our backend, in the shape Lexical's
 * CollaborationPlugin expects (compatible with y-websocket's provider).
 *
 * This is the Yjs protocol only: the sync handshake, updates, awareness and the
 * room's roster. The connection under it is the shared live socket
 * (`lib/liveSocket`) every channel uses — first-frame auth, jittered
 * reconnects, resuming when the network is back, and noticing a socket that
 * has gone quiet — so none of that is written again here.
 */

import type { Provider, ProviderAwareness, UserState } from "@lexical/yjs";
import { Awareness, applyAwarenessUpdate, encodeAwarenessUpdate } from "y-protocols/awareness";
import * as Y from "yjs";

import { getAuthToken } from "@/api/client";
import { type LiveSocket, openLiveSocket } from "@/lib/liveSocket";

// Message types matching the backend protocol
const MSG_SYNC_STEP1 = 0;
const MSG_SYNC_STEP2 = 1;
const MSG_UPDATE = 2;
const MSG_AWARENESS = 3;
const MSG_AWARENESS_BINARY = 4; // y-protocols awareness encoding
// 5 is the first frame's credential, which the live socket sends.
const MSG_CONTENT = 6; // The editor's JSON rendering, for the document's content column

/** What ``Y.encodeStateAsUpdate`` produces for a document with nothing in it.
 *  An answer to the server's SYNC_STEP1 that is this long carries no data, and
 *  sending one would mark the room unsaved over nothing. */
const EMPTY_UPDATE_LENGTH = Y.encodeStateAsUpdate(new Y.Doc()).length;

export interface CollaboratorInfo {
  user_id: number;
  name: string;
  can_write: boolean;
  /** The picture's URL — a path this server serves, or one linked from a
   *  single sign-on account. Needs ``resolveUploadUrl`` to become absolute. */
  avatar_url?: string | null;
}

/**
 * A collaboration failure, and whether the provider is still trying.
 *
 * ``recoverable`` separates losing the connection — a tunnel, a sleeping
 * laptop, a server restart — from being refused one. The first is a state the
 * provider works its way out of and the editor should degrade through; the
 * second is final, and latching collaboration off is the right response only
 * to that.
 */
export class CollaborationError extends Error {
  readonly recoverable: boolean;

  constructor(message: string, recoverable: boolean) {
    super(message);
    this.name = "CollaborationError";
    this.recoverable = recoverable;
  }
}

export interface CollaborationProviderOptions {
  connect?: boolean;
}

/** Closes in a row, without the socket opening in between, before the editor
 *  is told the connection is lost. The socket keeps trying after that. */
const LOST_AFTER_CLOSES = 5;

// Typed callback signatures matching Lexical's Provider interface
type SyncCallback = (isSynced: boolean) => void;
type StatusCallback = (status: { status: string }) => void;
type UpdateCallback = (update: unknown) => void;
type ReloadCallback = (doc: Y.Doc) => void;
type CollaboratorsCallback = (collaborators: CollaboratorInfo[]) => void;
type ErrorCallback = (error: Error) => void;

// The provider serving each address, so a remount joins the connection in
// progress rather than opening a second one.
const activeProviders = new Map<string, CollaborationProvider>();

/**
 * The provider already serving this address, if one is alive.
 *
 * A caller that is about to build a fresh Y.Doc asks this first: a provider
 * that is mid-handshake holds the only socket for that address, and the doc it
 * is bound to is the one the server is already answering. Taking that doc
 * instead of making another is what lets a remount join the connection in
 * progress rather than replace it.
 */
export function getLiveProvider(wsUrl: string): CollaborationProvider | null {
  const existing = activeProviders.get(new URL(wsUrl).pathname);
  return existing && !existing.destroyed ? existing : null;
}

/**
 * The provider for this address and doc. One bound to the same doc is reused
 * (React Strict Mode); one bound to another doc — Lexical makes a fresh one
 * after navigation — is replaced, or the editor would show an empty document.
 */
export function getOrCreateProvider(
  wsUrl: string,
  doc: Y.Doc,
  options: CollaborationProviderOptions = {}
): CollaborationProvider {
  const connectionId = new URL(wsUrl).pathname;
  const existing = activeProviders.get(connectionId);
  if (existing && !existing.destroyed && existing.doc === doc) {
    return existing;
  }
  existing?.destroy();
  const provider = new CollaborationProvider(wsUrl, doc, options, connectionId);
  activeProviders.set(connectionId, provider);
  return provider;
}

export class CollaborationProvider implements Provider {
  // Public properties expected by CollaborationPlugin
  public awareness: ProviderAwareness;
  public doc: Y.Doc;

  // Internal awareness instance
  private _awareness: Awareness;

  private socket: LiveSocket | null = null;
  private _open = false;
  private wsUrl: string;
  private connectionId: string;
  private disconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  public destroyed = false;
  private _synced = false;
  private _status: string = "disconnected";
  /** Closes since the socket last opened, for telling the editor the
   *  connection is lost; and whether it has been told, so it is told once
   *  however long the outage runs. */
  private closesSinceOpen = 0;
  private lostConnectionReported = false;

  // Typed event handlers
  private syncHandlers: Set<SyncCallback> = new Set();
  private statusHandlers: Set<StatusCallback> = new Set();
  private updateHandlers: Set<UpdateCallback> = new Set();
  private reloadHandlers: Set<ReloadCallback> = new Set();
  private collaboratorsHandlers: Set<CollaboratorsCallback> = new Set();
  private errorHandlers: Set<ErrorCallback> = new Set();

  // Current collaborators list
  private _collaborators: CollaboratorInfo[] = [];

  constructor(
    wsUrl: string,
    doc: Y.Doc,
    options: CollaborationProviderOptions = {},
    connectionId?: string
  ) {
    this.wsUrl = wsUrl;
    this.doc = doc;
    this._awareness = new Awareness(doc);
    this.connectionId = connectionId || new URL(wsUrl).pathname;

    // Create a ProviderAwareness wrapper that matches Lexical's expected interface
    this.awareness = {
      getLocalState: () => this._awareness.getLocalState() as UserState | null,
      getStates: () => this._awareness.getStates() as Map<number, UserState>,
      setLocalState: (state: UserState | null) => {
        if (state === null) {
          this._awareness.setLocalState(null);
          return;
        }
        // Set each field individually
        Object.entries(state).forEach(([key, value]) => {
          this._awareness.setLocalStateField(key, value);
        });
      },
      setLocalStateField: (field: string, value: unknown) => {
        this._awareness.setLocalStateField(field, value);
      },
      on: (type: "update", cb: () => void) => {
        if (type === "update") {
          this._awareness.on("change", cb);
        }
      },
      off: (type: "update", cb: () => void) => {
        if (type === "update") {
          this._awareness.off("change", cb);
        }
      },
    };

    // Listen for local doc changes to send to server
    this.doc.on("update", this.handleDocUpdate);

    // Listen for awareness changes
    this._awareness.on("change", this.handleAwarenessChange);

    if (options.connect !== false) {
      this.connect();
    }
  }

  /**
   * Try again now, with a fresh backoff — what to call when the network is
   * back and the socket should stop waiting out its retry schedule. The
   * socket also does this by itself on the browser's `online` event.
   */
  resume(): void {
    if (this.destroyed) return;
    this.closesSinceOpen = 0;
    this.lostConnectionReported = false;
    if (this.socket) {
      this.socket.resume();
    } else {
      this.connect();
    }
  }

  /**
   * Whether the provider has synced with the server.
   */
  get synced(): boolean {
    return this._synced;
  }

  /**
   * Whether the socket is currently open.
   */
  get connected(): boolean {
    return this._open;
  }

  /**
   * The current connection status.
   */
  get status(): string {
    return this._status;
  }

  /**
   * Open the room's socket, or keep the one already open. Cancels a pending
   * `disconnect`, which is what React Strict Mode's unmount/remount relies on.
   */
  connect(): void {
    if (this.destroyed) {
      return;
    }
    if (this.disconnectTimeout) {
      clearTimeout(this.disconnectTimeout);
      this.disconnectTimeout = null;
    }
    if (this.socket) {
      return;
    }
    this.emitStatus({ status: "connecting" });
    this.socket = openLiveSocket({
      url: this.wsUrl,
      // Read as each first frame is written: a document stays open across
      // renewals, and a reconnect presents what is current then. Null is fine
      // — the server reads the session cookie, which is the web path.
      auth: () => ({ token: getAuthToken() }),
      onBytes: this.handleFrame,
      onStatus: this.handleSocketStatus,
      onAuthRejected: this.handleRefused,
    });
  }

  /**
   * Close the room's socket, a moment from now: a `connect` in the meantime
   * (React Strict Mode's remount) keeps it open.
   */
  disconnect(): void {
    if (this.disconnectTimeout) {
      clearTimeout(this.disconnectTimeout);
    }
    this.disconnectTimeout = setTimeout(() => {
      this.disconnectTimeout = null;
      this.closeSocket();
      this.emitStatus({ status: "disconnected" });
    }, 100);
  }

  private closeSocket(): void {
    const socket = this.socket;
    // Forgotten first, so the close it causes is not read as a dropped
    // connection to recover from.
    this.socket = null;
    this._open = false;
    socket?.close();
    if (this._synced) {
      this._synced = false;
      this.emitSync(false);
    }
  }

  /**
   * Clean up all resources.
   */
  destroy(): void {
    if (this.destroyed) {
      return;
    }
    this.destroyed = true;

    if (activeProviders.get(this.connectionId) === this) {
      activeProviders.delete(this.connectionId);
    }
    if (this.disconnectTimeout) {
      clearTimeout(this.disconnectTimeout);
      this.disconnectTimeout = null;
    }
    this.closeSocket();

    this.doc.off("update", this.handleDocUpdate);
    this._awareness.off("change", this.handleAwarenessChange);
    this._awareness.destroy();
    this.syncHandlers.clear();
    this.statusHandlers.clear();
    this.updateHandlers.clear();
    this.reloadHandlers.clear();
    this.collaboratorsHandlers.clear();
    this.errorHandlers.clear();
    this._collaborators = [];
  }

  // Typed on/off methods matching Lexical's Provider interface
  on(type: "sync", cb: SyncCallback): void;
  on(type: "status", cb: StatusCallback): void;
  on(type: "update", cb: UpdateCallback): void;
  on(type: "reload", cb: ReloadCallback): void;
  on(type: "error", cb: ErrorCallback): void;
  on(
    type: "sync" | "status" | "update" | "reload" | "error",
    cb: SyncCallback | StatusCallback | UpdateCallback | ReloadCallback | ErrorCallback
  ): void {
    switch (type) {
      case "sync":
        this.syncHandlers.add(cb as SyncCallback);
        // If already synced, call immediately
        if (this._synced) {
          (cb as SyncCallback)(true);
        }
        break;
      case "status":
        this.statusHandlers.add(cb as StatusCallback);
        break;
      case "update":
        this.updateHandlers.add(cb as UpdateCallback);
        break;
      case "reload":
        this.reloadHandlers.add(cb as ReloadCallback);
        break;
      case "error":
        this.errorHandlers.add(cb as ErrorCallback);
        break;
    }
  }

  off(type: "sync", cb: SyncCallback): void;
  off(type: "status", cb: StatusCallback): void;
  off(type: "update", cb: UpdateCallback): void;
  off(type: "reload", cb: ReloadCallback): void;
  off(type: "error", cb: ErrorCallback): void;
  off(
    type: "sync" | "status" | "update" | "reload" | "error",
    cb: SyncCallback | StatusCallback | UpdateCallback | ReloadCallback | ErrorCallback
  ): void {
    switch (type) {
      case "sync":
        this.syncHandlers.delete(cb as SyncCallback);
        break;
      case "status":
        this.statusHandlers.delete(cb as StatusCallback);
        break;
      case "update":
        this.updateHandlers.delete(cb as UpdateCallback);
        break;
      case "reload":
        this.reloadHandlers.delete(cb as ReloadCallback);
        break;
      case "error":
        this.errorHandlers.delete(cb as ErrorCallback);
        break;
    }
  }

  /**
   * Get the current list of collaborators.
   */
  get collaborators(): CollaboratorInfo[] {
    return this._collaborators;
  }

  /**
   * Subscribe to collaborator changes.
   */
  onCollaborators(cb: CollaboratorsCallback): void {
    this.collaboratorsHandlers.add(cb);
    // Call immediately with current state
    if (this._collaborators.length > 0) {
      cb(this._collaborators);
    }
  }

  /**
   * Unsubscribe from collaborator changes.
   */
  offCollaborators(cb: CollaboratorsCallback): void {
    this.collaboratorsHandlers.delete(cb);
  }

  // Typed emit methods
  private emitSync(isSynced: boolean): void {
    this.syncHandlers.forEach((cb) => {
      try {
        cb(isSynced);
      } catch {
        // Ignore handler errors
      }
    });
  }

  private emitStatus(status: { status: string }): void {
    this._status = status.status;
    this.statusHandlers.forEach((cb) => {
      try {
        cb(status);
      } catch {
        // Ignore handler errors
      }
    });
  }

  private emitUpdate(update: unknown): void {
    this.updateHandlers.forEach((cb) => {
      try {
        cb(update);
      } catch {
        // Ignore handler errors
      }
    });
  }

  private emitCollaborators(): void {
    this.collaboratorsHandlers.forEach((cb) => {
      try {
        cb(this._collaborators);
      } catch {
        // Ignore handler errors
      }
    });
  }

  private emitError(error: Error): void {
    this.emitStatus({ status: "error" });
    this.errorHandlers.forEach((cb) => {
      try {
        cb(error);
      } catch {
        // Ignore handler errors
      }
    });
  }

  private handleSocketStatus = (open: boolean): void => {
    if (this.socket === null) return;
    this._open = open;
    if (open) {
      this.closesSinceOpen = 0;
      this.lostConnectionReported = false;
      this.emitStatus({ status: "connected" });
      // Ask for what the room has that this doc does not. The room asks the
      // same of us, so one connect settles both directions.
      this.sendMessage(MSG_SYNC_STEP1, Y.encodeStateVector(this.doc));
      return;
    }
    if (this._synced) {
      this._synced = false;
      this.emitSync(false);
    }
    // The socket is already trying again. Past a few closes the editor is
    // told — once — that it is on its own for now; the work done meanwhile
    // reaches the room through the sync handshake the moment it is back.
    this.closesSinceOpen += 1;
    if (this.closesSinceOpen >= LOST_AFTER_CLOSES && !this.lostConnectionReported) {
      this.lostConnectionReported = true;
      this.emitError(new CollaborationError("Connection lost. Still trying to reconnect.", true));
    }
    this.emitStatus({ status: "connecting" });
  };

  /** The room refused this reader repeatedly: final, unlike a lost connection. */
  private handleRefused = (): void => {
    this.closeSocket();
    this.emitError(new CollaborationError("Authentication failed or access denied", false));
  };

  private handleFrame = (data: Uint8Array): void => {
    if (data.length < 1) return;

    const msgType = data[0];
    const payload = data.slice(1);

    switch (msgType) {
      case MSG_SYNC_STEP1: {
        // The server is asking for whatever we have that it doesn't. This is
        // the other half of the handshake, and the one path by which state
        // this client already holds travels upstream — every other frame we
        // send is an increment on top of state the server is known to have.
        const update =
          payload.length > 0
            ? Y.encodeStateAsUpdate(this.doc, payload)
            : Y.encodeStateAsUpdate(this.doc);
        if (update.length > EMPTY_UPDATE_LENGTH) {
          this.sendMessage(MSG_SYNC_STEP2, update);
        }
        break;
      }

      case MSG_SYNC_STEP2:
        // Apply server state - always call applyUpdate, Yjs handles empty updates gracefully
        Y.applyUpdate(this.doc, payload, this);
        if (!this._synced) {
          this._synced = true;
          this.emitSync(true);
        }
        break;

      case MSG_UPDATE:
        // Apply incremental update from another client
        if (payload.length > 0) {
          Y.applyUpdate(this.doc, payload, this);
          this.emitUpdate(payload);
        }
        break;

      case MSG_AWARENESS:
        // Handle awareness message (JSON) - server-side messages like join/leave
        try {
          const json = new TextDecoder().decode(payload);
          const message = JSON.parse(json);
          this.handleAwarenessMessage(message);
        } catch {
          // Ignore parse errors
        }
        break;

      case MSG_AWARENESS_BINARY:
        // Apply y-protocols awareness update from another client
        // This enables cursor synchronization
        try {
          applyAwarenessUpdate(this._awareness, payload, this);
        } catch {
          // Ignore awareness update errors
        }
        break;
    }
  };

  private handleDocUpdate = (update: Uint8Array, origin: unknown): void => {
    // Don't echo back updates from the server (origin === this)
    if (origin === this) return;

    this.sendMessage(MSG_UPDATE, update);
  };

  private handleAwarenessChange = (): void => {
    // Only send awareness updates after initial sync to avoid accessing uninitialized Yjs types
    if (!this._synced) return;

    // Send awareness update in y-protocols binary format
    // This enables proper cursor synchronization across clients
    const update = encodeAwarenessUpdate(this._awareness, [this.doc.clientID]);
    this.sendMessage(MSG_AWARENESS_BINARY, update);
  };

  private handleAwarenessMessage(message: Record<string, unknown>): void {
    const msgType = message.type as string;

    // Handle wrapped awareness messages from broadcast_awareness
    // Format: {"type": "awareness", "data": {"type": "join"|"leave"|"cursor", ...}}
    if (
      msgType === "awareness" &&
      message.data &&
      typeof message.data === "object" &&
      !Array.isArray(message.data)
    ) {
      this.handleInnerAwarenessMessage(message.data as Record<string, unknown>);
      return;
    }

    // Handle direct messages (like collaborators list)
    this.handleInnerAwarenessMessage(message);
  }

  private handleInnerAwarenessMessage(message: Record<string, unknown>): void {
    const msgType = message.type as string;

    // Update collaborators based on server messages
    switch (msgType) {
      case "collaborators": {
        // Full collaborator list from server
        const data = message.data;
        if (data && Array.isArray(data)) {
          this._collaborators = data as CollaboratorInfo[];
          this.emitCollaborators();
        }
        break;
      }

      case "join": {
        // A user joined - add them if not already present
        const user = message.user as
          | {
              user_id: number;
              name: string;
              avatar_url?: string | null;
            }
          | undefined;
        if (user) {
          const exists = this._collaborators.some((c) => c.user_id === user.user_id);
          if (!exists) {
            this._collaborators = [
              ...this._collaborators,
              {
                user_id: user.user_id,
                name: user.name,
                can_write: true, // Default to true, server will correct if needed
                avatar_url: user.avatar_url ?? null,
              },
            ];
            this.emitCollaborators();
          }
        }
        break;
      }

      case "leave": {
        // A user left - remove them from the list
        const userId = message.user_id as number | undefined;
        if (userId !== undefined) {
          const before = this._collaborators.length;
          this._collaborators = this._collaborators.filter((c) => c.user_id !== userId);
          if (this._collaborators.length !== before) {
            this.emitCollaborators();
          }
        }
        break;
      }
    }
  }

  /**
   * Report the editor's JSON rendering of the document to its room.
   *
   * The room writes this alongside the Yjs state, from one snapshot, so the
   * document's two stored views always describe the same moment. Only sent
   * once synced: before that this client's doc is not yet the room's.
   */
  sendContent(content: unknown): void {
    if (!this._synced) return;
    this.sendMessage(MSG_CONTENT, new TextEncoder().encode(JSON.stringify(content)));
  }

  private sendMessage(type: number, payload: Uint8Array): void {
    const message = new Uint8Array(1 + payload.length);
    message[0] = type;
    message.set(payload, 1);
    this.socket?.send(message);
  }
}
