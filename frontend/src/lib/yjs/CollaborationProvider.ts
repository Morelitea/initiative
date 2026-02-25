/**
 * WebSocket provider for Yjs collaboration with our backend.
 *
 * This provider implements the interface expected by Lexical's CollaborationPlugin,
 * which is compatible with y-websocket's WebsocketProvider.
 *
 * Handles:
 * - WebSocket connection lifecycle
 * - Yjs sync protocol
 * - Awareness (cursor presence)
 * - Automatic reconnection
 */

import * as Y from "yjs";
import { Awareness, encodeAwarenessUpdate, applyAwarenessUpdate } from "y-protocols/awareness";
import type { Provider, UserState, ProviderAwareness } from "@lexical/yjs";

// Message types matching the backend protocol
const MSG_SYNC_STEP1 = 0;
const MSG_SYNC_STEP2 = 1;
const MSG_UPDATE = 2;
const MSG_AWARENESS = 3;
const MSG_AWARENESS_BINARY = 4; // y-protocols awareness encoding
const MSG_AUTH = 5; // Authentication message (sent first after connect)

export interface CollaboratorInfo {
  user_id: number;
  name: string;
  can_write: boolean;
  cursor?: {
    anchor: { path: number[]; offset: number };
    focus: { path: number[]; offset: number };
  } | null;
}

export interface CollaborationProviderOptions {
  connect?: boolean;
  /** Auth params sent via MSG_AUTH message after connection (not in URL for security) */
  auth?: {
    token: string | null;
    guildId: number;
  };
}

// Typed callback signatures matching Lexical's Provider interface
type SyncCallback = (isSynced: boolean) => void;
type StatusCallback = (status: { status: string }) => void;
type UpdateCallback = (update: unknown) => void;
type ReloadCallback = (doc: Y.Doc) => void;
type CollaboratorsCallback = (collaborators: CollaboratorInfo[]) => void;
type ErrorCallback = (error: Error) => void;

/**
 * WebSocket provider implementing Lexical's Provider interface.
 * This allows it to work with Lexical's CollaborationPlugin.
 */
// Global connection tracking to prevent rapid reconnection loops
const activeProviders = new Map<string, CollaborationProvider>();
const connectionAttempts = new Map<string, { count: number; lastAttempt: number }>();
const MAX_ATTEMPTS_PER_MINUTE = 10;

/**
 * Get or create a CollaborationProvider for the given URL.
 * This ensures we only have one active provider per document.
 *
 * Important: We only reuse a provider if the Y.Doc matches. If the doc is different
 * (e.g., after navigation when Lexical creates a fresh yjsDocMap), we create a new provider.
 * This prevents the issue where the editor appears empty because the old provider's
 * Y.Doc doesn't match Lexical's new Y.Doc.
 */
export function getOrCreateProvider(
  wsUrl: string,
  roomName: string,
  doc: Y.Doc,
  options: CollaborationProviderOptions = {}
): CollaborationProvider {
  // Create a connection ID based on the path (without token for consistency)
  const urlObj = new URL(wsUrl);
  const connectionId = urlObj.pathname;

  // Check if there's already an active provider with the SAME doc
  const existingProvider = activeProviders.get(connectionId);
  if (existingProvider && !existingProvider.destroyed && existingProvider.doc === doc) {
    // Same doc - reuse provider (React Strict Mode case)
    return existingProvider;
  }

  // Different doc or destroyed provider - clean up old and create new
  if (existingProvider) {
    existingProvider.destroy();
    activeProviders.delete(connectionId);
  }

  const provider = new CollaborationProvider(wsUrl, roomName, doc, options, connectionId);
  activeProviders.set(connectionId, provider);
  return provider;
}

export class CollaborationProvider implements Provider {
  // Public properties expected by CollaborationPlugin
  public awareness: ProviderAwareness;
  public doc: Y.Doc;

  // Internal awareness instance
  private _awareness: Awareness;

  private websocket: WebSocket | null = null;
  private wsUrl: string;
  private roomName: string;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private disconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  public destroyed = false;
  private _synced = false;
  private _status: string = "disconnected";
  private shouldConnect: boolean;
  private connectionId: string;
  private authParams: { token: string | null; guildId: number } | null = null;

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
    roomName: string,
    doc: Y.Doc,
    options: CollaborationProviderOptions = {},
    connectionId?: string
  ) {
    this.wsUrl = wsUrl;
    this.roomName = roomName;
    this.doc = doc;
    this._awareness = new Awareness(doc);
    this.shouldConnect = options.connect !== false;
    this.connectionId = connectionId || new URL(wsUrl).pathname;
    this.authParams = options.auth || null;

    // Create a ProviderAwareness wrapper that matches Lexical's expected interface
    this.awareness = {
      getLocalState: () => this._awareness.getLocalState() as UserState | null,
      getStates: () => this._awareness.getStates() as Map<number, UserState>,
      setLocalState: (state: UserState) => {
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

    // Auto-connect if not disabled
    if (this.shouldConnect) {
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
   * Whether the WebSocket is currently connected.
   */
  get connected(): boolean {
    return this.websocket?.readyState === WebSocket.OPEN;
  }

  /**
   * The current connection status.
   */
  get status(): string {
    return this._status;
  }

  /**
   * Connect to the collaboration WebSocket.
   */
  connect(): void {
    if (this.destroyed) {
      return;
    }

    // Cancel any pending disconnect (React Strict Mode handling)
    if (this.cancelPendingDisconnect()) {
      // If we had a pending disconnect and the websocket is still good, just return
      if (this.websocket) {
        const state = this.websocket.readyState;
        if (state === WebSocket.CONNECTING || state === WebSocket.OPEN) {
          return;
        }
      }
    }

    if (this.websocket) {
      const state = this.websocket.readyState;
      if (state === WebSocket.CONNECTING || state === WebSocket.OPEN) {
        return;
      }
      // Close stale WebSocket before creating new one
      this.websocket.close();
      this.websocket = null;
    }

    // Rate limiting: prevent rapid reconnection attempts
    const now = Date.now();
    const attempts = connectionAttempts.get(this.connectionId) || { count: 0, lastAttempt: 0 };
    const timeSinceLastAttempt = now - attempts.lastAttempt;

    // Reset counter after 1 minute
    if (timeSinceLastAttempt > 60000) {
      attempts.count = 0;
    }

    // Check if we've exceeded the rate limit
    if (attempts.count >= MAX_ATTEMPTS_PER_MINUTE) {
      // Schedule retry after the rate limit window resets
      const timeUntilReset = 60000 - timeSinceLastAttempt;
      // Don't check shouldConnect here - if connect() was called, caller wants to connect
      if (timeUntilReset > 0 && !this.destroyed) {
        this.emitStatus({ status: "connecting" });
        this.reconnectTimeout = setTimeout(() => {
          this.reconnectTimeout = null;
          this.connect();
        }, timeUntilReset);
      } else {
        this.emitStatus({ status: "disconnected" });
      }
      return;
    }

    // Update attempt tracking
    attempts.count++;
    attempts.lastAttempt = now;
    connectionAttempts.set(this.connectionId, attempts);

    this.emitStatus({ status: "connecting" });

    try {
      this.websocket = new WebSocket(this.wsUrl);
      this.websocket.binaryType = "arraybuffer";

      this.websocket.onopen = this.handleOpen;
      this.websocket.onmessage = this.handleMessage;
      this.websocket.onclose = this.handleClose;
      this.websocket.onerror = this.handleError;
    } catch {
      this.emitStatus({ status: "disconnected" });
    }
  }

  /**
   * Disconnect from the collaboration WebSocket.
   * Uses a small delay to handle React Strict Mode's unmount/remount cycle.
   */
  disconnect(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    // Debounce disconnect to handle React Strict Mode
    // If connect() is called within 100ms, we'll cancel this disconnect
    if (this.disconnectTimeout) {
      clearTimeout(this.disconnectTimeout);
    }

    this.disconnectTimeout = setTimeout(() => {
      this.disconnectTimeout = null;
      if (this.websocket) {
        this.websocket.close();
        this.websocket = null;
      }
      this._synced = false;
      this.emitStatus({ status: "disconnected" });
    }, 100);
  }

  /**
   * Cancel any pending disconnect (called when connect() is invoked).
   */
  private cancelPendingDisconnect(): boolean {
    if (this.disconnectTimeout) {
      clearTimeout(this.disconnectTimeout);
      this.disconnectTimeout = null;
      return true;
    }
    return false;
  }

  /**
   * Clean up all resources.
   */
  destroy(): void {
    if (this.destroyed) {
      return;
    }
    this.destroyed = true;

    // Remove from global tracking
    if (activeProviders.get(this.connectionId) === this) {
      activeProviders.delete(this.connectionId);
    }

    // Clear any pending timeouts
    if (this.disconnectTimeout) {
      clearTimeout(this.disconnectTimeout);
      this.disconnectTimeout = null;
    }
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    // Immediately close WebSocket (no debounce for destroy)
    if (this.websocket) {
      this.websocket.close();
      this.websocket = null;
    }

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

  private handleOpen = (): void => {
    this.reconnectAttempts = 0;

    // Send authentication message first (required by server)
    if (this.authParams) {
      const authPayload = JSON.stringify({
        token: this.authParams.token,
        guild_id: this.authParams.guildId,
      });
      this.sendMessage(MSG_AUTH, new TextEncoder().encode(authPayload));
    }

    this.emitStatus({ status: "connected" });

    // Request initial sync - send empty state vector to get full state
    const stateVector = Y.encodeStateVector(this.doc);
    this.sendMessage(MSG_SYNC_STEP1, stateVector);
  };

  private handleMessage = (event: MessageEvent): void => {
    const data = new Uint8Array(event.data as ArrayBuffer);
    if (data.length < 1) return;

    const msgType = data[0];
    const payload = data.slice(1);

    switch (msgType) {
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

  private handleClose = (event: CloseEvent): void => {
    this.websocket = null;
    this._synced = false;
    this.emitSync(false);

    // Code 1008 = Policy Violation (used for auth failures)
    const wasAuthFailure = event.code === 1008;

    if (wasAuthFailure) {
      this.emitError(new Error("Authentication failed or access denied"));
    } else if (this.shouldConnect && !this.destroyed) {
      // Not an auth failure and we should stay connected - try to reconnect
      this.emitStatus({ status: "disconnected" });
      this.scheduleReconnect();
    } else {
      this.emitStatus({ status: "disconnected" });
    }
  };

  private handleError = (): void => {
    // Don't emit error here - this fires for transient network issues
    // handleClose will be called next and will either reconnect or emit a fatal error
    // Only fatal errors (auth failure, max retries) should trigger the error event
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
        const user = message.user as { user_id: number; name: string } | undefined;
        if (user) {
          const exists = this._collaborators.some((c) => c.user_id === user.user_id);
          if (!exists) {
            this._collaborators = [
              ...this._collaborators,
              {
                user_id: user.user_id,
                name: user.name,
                can_write: true, // Default to true, server will correct if needed
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

      case "cursor":
        // Cursor position update - handled by Lexical's built-in cursor support
        break;
    }
  }

  private sendMessage(type: number, payload: Uint8Array): void {
    if (!this.websocket || this.websocket.readyState !== WebSocket.OPEN) {
      return;
    }

    const message = new Uint8Array(1 + payload.length);
    message[0] = type;
    message.set(payload, 1);
    this.websocket.send(message);
  }

  private scheduleReconnect(): void {
    if (this.destroyed) {
      return;
    }

    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      // Max retries exceeded - emit error
      this.emitError(new Error("Connection lost. Maximum reconnection attempts reached."));
      return;
    }

    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts - 1), 30000);

    // Emit connecting status while waiting to reconnect
    this.emitStatus({ status: "connecting" });

    this.reconnectTimeout = setTimeout(() => {
      this.reconnectTimeout = null;
      this.connect();
    }, delay);
  }
}
