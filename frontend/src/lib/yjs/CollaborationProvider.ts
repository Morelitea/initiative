/**
 * WebSocket provider for Yjs collaboration with our backend.
 *
 * Handles:
 * - WebSocket connection lifecycle
 * - Yjs sync protocol
 * - Awareness (cursor presence)
 * - Automatic reconnection
 */

import * as Y from "yjs";
import { Awareness } from "y-protocols/awareness";

// Message types matching the backend protocol
const MSG_SYNC_STEP1 = 0;
const MSG_SYNC_STEP2 = 1;
const MSG_UPDATE = 2;
const MSG_AWARENESS = 3;

export interface CollaboratorInfo {
  user_id: number;
  name: string;
  can_write: boolean;
  cursor?: {
    anchor: { path: number[]; offset: number };
    focus: { path: number[]; offset: number };
  } | null;
}

export interface CollaborationProviderConfig {
  documentId: number;
  guildId: number;
  token: string;
  baseUrl: string;
  onSynced?: () => void;
  onDisconnected?: () => void;
  onCollaboratorsChange?: (collaborators: CollaboratorInfo[]) => void;
  onConnectionStatusChange?: (status: ConnectionStatus) => void;
}

export type ConnectionStatus = "connecting" | "connected" | "disconnected" | "error";

export class CollaborationProvider {
  private doc: Y.Doc;
  private awareness: Awareness;
  private websocket: WebSocket | null = null;
  private config: CollaborationProviderConfig;
  private connectionStatus: ConnectionStatus = "disconnected";
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private collaborators: CollaboratorInfo[] = [];
  private destroyed = false;
  private synced = false;

  constructor(doc: Y.Doc, config: CollaborationProviderConfig) {
    this.doc = doc;
    this.config = config;
    this.awareness = new Awareness(doc);

    // Listen for local doc changes
    this.doc.on("update", this.handleDocUpdate);

    // Listen for awareness changes
    this.awareness.on("change", this.handleAwarenessChange);
  }

  /**
   * Connect to the collaboration WebSocket.
   */
  connect(): void {
    if (this.destroyed) return;

    this.setConnectionStatus("connecting");
    const wsUrl = this.buildWebSocketUrl();

    try {
      this.websocket = new WebSocket(wsUrl);
      this.websocket.binaryType = "arraybuffer";

      this.websocket.onopen = this.handleOpen;
      this.websocket.onmessage = this.handleMessage;
      this.websocket.onclose = this.handleClose;
      this.websocket.onerror = this.handleError;
    } catch (error) {
      console.error("CollaborationProvider: Failed to create WebSocket", error);
      this.setConnectionStatus("error");
      this.scheduleReconnect();
    }
  }

  /**
   * Disconnect from the collaboration WebSocket.
   */
  disconnect(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.websocket) {
      this.websocket.close();
      this.websocket = null;
    }

    this.setConnectionStatus("disconnected");
  }

  /**
   * Clean up all resources.
   */
  destroy(): void {
    this.destroyed = true;
    this.disconnect();
    this.doc.off("update", this.handleDocUpdate);
    this.awareness.off("change", this.handleAwarenessChange);
    this.awareness.destroy();
  }

  /**
   * Get the Yjs document.
   */
  getDoc(): Y.Doc {
    return this.doc;
  }

  /**
   * Get the awareness instance for cursor presence.
   */
  getAwareness(): Awareness {
    return this.awareness;
  }

  /**
   * Get the current connection status.
   */
  getConnectionStatus(): ConnectionStatus {
    return this.connectionStatus;
  }

  /**
   * Get the current list of collaborators.
   */
  getCollaborators(): CollaboratorInfo[] {
    return this.collaborators;
  }

  /**
   * Check if the initial sync is complete.
   */
  isSynced(): boolean {
    return this.synced;
  }

  /**
   * Set the local user's awareness state (cursor, name, etc.)
   */
  setLocalAwareness(state: Record<string, unknown>): void {
    this.awareness.setLocalStateField("user", state);
  }

  private buildWebSocketUrl(): string {
    const { baseUrl, documentId, token, guildId } = this.config;

    // Handle both absolute and relative URLs
    // Use window.location.origin as base for relative URLs
    const isAbsolute = baseUrl.startsWith("http://") || baseUrl.startsWith("https://");
    const url = isAbsolute ? new URL(baseUrl) : new URL(baseUrl, window.location.origin);

    // Convert HTTP to WebSocket protocol
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";

    // Build the collaboration endpoint path
    const normalizedPath = url.pathname.endsWith("/")
      ? url.pathname.slice(0, -1)
      : url.pathname || "/api/v1";

    url.pathname = `${normalizedPath}/collaboration/documents/${documentId}/collaborate`;
    url.searchParams.set("token", token);
    url.searchParams.set("guild_id", String(guildId));

    return url.toString();
  }

  private handleOpen = (): void => {
    console.log("CollaborationProvider: Connected");
    this.reconnectAttempts = 0;
    this.setConnectionStatus("connected");

    // Request initial sync
    this.sendMessage(MSG_SYNC_STEP1, new Uint8Array(0));
  };

  private handleMessage = (event: MessageEvent): void => {
    const data = new Uint8Array(event.data as ArrayBuffer);
    if (data.length < 1) return;

    const msgType = data[0];
    const payload = data.slice(1);

    switch (msgType) {
      case MSG_SYNC_STEP2:
        // Apply server state
        if (payload.length > 0) {
          Y.applyUpdate(this.doc, payload, "server");
        }
        if (!this.synced) {
          this.synced = true;
          this.config.onSynced?.();
        }
        break;

      case MSG_UPDATE:
        // Apply incremental update
        if (payload.length > 0) {
          Y.applyUpdate(this.doc, payload, "server");
        }
        break;

      case MSG_AWARENESS:
        // Handle awareness message (JSON)
        try {
          const json = new TextDecoder().decode(payload);
          const message = JSON.parse(json);
          this.handleAwarenessMessage(message);
        } catch (e) {
          console.warn("CollaborationProvider: Failed to parse awareness message", e);
        }
        break;
    }
  };

  private handleClose = (event: CloseEvent): void => {
    console.log("CollaborationProvider: Disconnected", event.code, event.reason);
    this.websocket = null;
    this.synced = false;

    if (event.code === 1008) {
      // Policy violation (auth failure) - don't reconnect
      this.setConnectionStatus("error");
      this.config.onDisconnected?.();
      return;
    }

    this.setConnectionStatus("disconnected");
    this.config.onDisconnected?.();
    this.scheduleReconnect();
  };

  private handleError = (event: Event): void => {
    console.error("CollaborationProvider: WebSocket error", event);
    // The close handler will be called after this
  };

  private handleDocUpdate = (update: Uint8Array, origin: unknown): void => {
    // Don't echo back updates from the server
    if (origin === "server") return;

    // Send to server
    this.sendMessage(MSG_UPDATE, update);
  };

  private handleAwarenessChange = (): void => {
    // Send local awareness state to server
    const localState = this.awareness.getLocalState();
    if (localState) {
      const json = JSON.stringify(localState);
      const payload = new TextEncoder().encode(json);
      this.sendMessage(MSG_AWARENESS, payload);
    }
  };

  private handleAwarenessMessage(message: {
    type: string;
    data?: CollaboratorInfo[];
    user_id?: number;
    user?: { user_id: number; name: string };
    cursor?: unknown;
  }): void {
    switch (message.type) {
      case "collaborators":
        // Full collaborator list
        this.collaborators = message.data || [];
        this.config.onCollaboratorsChange?.(this.collaborators);
        break;

      case "join":
        // New collaborator joined
        if (message.user) {
          const existing = this.collaborators.find((c) => c.user_id === message.user!.user_id);
          if (!existing) {
            this.collaborators = [
              ...this.collaborators,
              { ...message.user, can_write: true, cursor: null },
            ];
            this.config.onCollaboratorsChange?.(this.collaborators);
          }
        }
        break;

      case "leave":
        // Collaborator left
        if (message.user_id) {
          this.collaborators = this.collaborators.filter((c) => c.user_id !== message.user_id);
          this.config.onCollaboratorsChange?.(this.collaborators);
        }
        break;

      case "cursor":
        // Cursor position update
        if (message.user_id) {
          this.collaborators = this.collaborators.map((c) =>
            c.user_id === message.user_id
              ? { ...c, cursor: message.cursor as CollaboratorInfo["cursor"] }
              : c
          );
          this.config.onCollaboratorsChange?.(this.collaborators);
        }
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

  private setConnectionStatus(status: ConnectionStatus): void {
    if (this.connectionStatus !== status) {
      this.connectionStatus = status;
      this.config.onConnectionStatusChange?.(status);
    }
  }

  private scheduleReconnect(): void {
    if (this.destroyed || this.reconnectAttempts >= this.maxReconnectAttempts) {
      return;
    }

    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts - 1), 30000);

    console.log(
      `CollaborationProvider: Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`
    );

    this.reconnectTimeout = setTimeout(() => {
      this.reconnectTimeout = null;
      this.connect();
    }, delay);
  }
}
