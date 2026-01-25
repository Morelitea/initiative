/**
 * React hook for managing collaborative document editing sessions.
 *
 * Handles:
 * - Yjs document and provider lifecycle
 * - Connection state tracking
 * - Collaborator presence
 * - Fallback to autosave mode
 *
 * This hook is designed to work with Lexical's official CollaborationPlugin.
 * It provides a providerFactory that the plugin calls to get the WebSocket provider.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as Y from "yjs";

import { API_BASE_URL } from "@/api/client";
import { useAuth } from "./useAuth";
import { useGuilds } from "./useGuilds";
import {
  CollaborationProvider,
  CollaboratorInfo,
  getOrCreateProvider,
} from "@/lib/yjs/CollaborationProvider";

export type ConnectionStatus = "disconnected" | "connecting" | "connected" | "error";

export interface UseCollaborationOptions {
  documentId: number;
  enabled?: boolean;
  onSynced?: () => void;
  onError?: (error: Error) => void;
}

export interface UseCollaborationResult {
  /**
   * Factory function for Lexical's CollaborationPlugin.
   * Returns null if collaboration is not ready (missing auth, guild, etc.)
   */
  providerFactory: ((id: string, yjsDocMap: Map<string, Y.Doc>) => CollaborationProvider) | null;
  /** Current connection status */
  connectionStatus: ConnectionStatus;
  /** Whether the initial sync is complete */
  isSynced: boolean;
  /** List of current collaborators */
  collaborators: CollaboratorInfo[];
  /** Whether collaboration is active (connected and synced) */
  isCollaborating: boolean;
  /** Whether the hook is ready to provide collaboration */
  isReady: boolean;
  /** Manually connect to the collaboration session */
  connect: () => void;
  /** Manually disconnect from the collaboration session */
  disconnect: () => void;
}

export function useCollaboration({
  documentId,
  enabled = true,
  onSynced,
  onError,
}: UseCollaborationOptions): UseCollaborationResult {
  console.log("useCollaboration: Hook called with documentId:", documentId, "enabled:", enabled);

  const { token } = useAuth();
  const { activeGuildId } = useGuilds();

  console.log(
    "useCollaboration: token:",
    token ? "present" : "missing",
    "activeGuildId:",
    activeGuildId
  );

  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("disconnected");
  const [isSynced, setIsSynced] = useState(false);
  const [collaborators, setCollaborators] = useState<CollaboratorInfo[]>([]);

  // Store the provider reference so we can track its state
  const providerRef = useRef<CollaborationProvider | null>(null);
  // Track the current WebSocket URL to detect when it changes
  const currentWsUrlRef = useRef<string | null>(null);

  // Create stable callback refs
  const onSyncedRef = useRef(onSynced);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onSyncedRef.current = onSynced;
    onErrorRef.current = onError;
  }, [onSynced, onError]);

  // Check if we have all required values
  const isReady = Boolean(enabled && token && activeGuildId && documentId);

  // Build the WebSocket URL (memoized to detect changes)
  const wsUrl = useMemo(() => {
    if (!isReady || !token || !activeGuildId) {
      return null;
    }
    // Build WebSocket URL - use Vite's proxy in development
    const isAbsolute = API_BASE_URL.startsWith("http://") || API_BASE_URL.startsWith("https://");
    const url = isAbsolute ? new URL(API_BASE_URL) : new URL(API_BASE_URL, window.location.origin);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const normalizedPath = url.pathname.endsWith("/")
      ? url.pathname.slice(0, -1)
      : url.pathname || "/api/v1";
    url.pathname = `${normalizedPath}/collaboration/documents/${documentId}/collaborate`;
    url.searchParams.set("token", token);
    url.searchParams.set("guild_id", String(activeGuildId));
    return url.toString();
  }, [isReady, token, activeGuildId, documentId]);

  // Clean up provider when URL changes (token refresh, guild change, etc.)
  useEffect(() => {
    if (currentWsUrlRef.current && currentWsUrlRef.current !== wsUrl) {
      console.log("useCollaboration: WebSocket URL changed, destroying old provider");
      providerRef.current?.destroy();
      providerRef.current = null;
    }
    currentWsUrlRef.current = wsUrl;
  }, [wsUrl]);

  // Create the provider factory that Lexical's CollaborationPlugin will call
  const providerFactory = useMemo(() => {
    if (!wsUrl) {
      console.log("useCollaboration: Not ready, providerFactory is null");
      return null;
    }

    console.log("useCollaboration: Creating providerFactory for documentId:", documentId);

    // Return the factory function that CollaborationPlugin expects
    return (id: string, yjsDocMap: Map<string, Y.Doc>): CollaborationProvider => {
      console.log("useCollaboration: providerFactory called with id:", id);

      // Check if we already have a provider with the same URL
      if (providerRef.current && currentWsUrlRef.current === wsUrl) {
        console.log("useCollaboration: Returning existing provider");
        // Ensure provider is connected (cancels pending disconnect or reconnects)
        providerRef.current.connect();
        return providerRef.current;
      }

      // Destroy any existing provider first
      if (providerRef.current) {
        console.log("useCollaboration: Destroying stale provider before creating new one");
        providerRef.current.destroy();
        providerRef.current = null;
      }

      // Get or create the Y.Doc
      let doc = yjsDocMap.get(id);
      if (doc === undefined) {
        doc = new Y.Doc();
        yjsDocMap.set(id, doc);
        console.log("useCollaboration: Created new Y.Doc, clientID:", doc.clientID);
      } else {
        console.log("useCollaboration: Using existing Y.Doc, clientID:", doc.clientID);
      }

      // Log URL details for debugging
      const urlObj = new URL(wsUrl);
      console.log("useCollaboration: Getting/creating provider", {
        protocol: urlObj.protocol,
        host: urlObj.host,
        pathname: urlObj.pathname,
        hasToken: urlObj.searchParams.has("token"),
        guildId: urlObj.searchParams.get("guild_id"),
      });

      // Use the factory function to get or create a provider
      // This ensures we reuse existing providers for the same document
      const provider = getOrCreateProvider(wsUrl, id, doc, { connect: true });

      // Ensure provider is connected (handles reconnecting after navigation)
      provider.connect();

      // Check if this is a new provider (not already in providerRef.current)
      const existingProvider = providerRef.current;
      const isNewProvider = existingProvider !== provider;

      // Store reference so we can track state
      providerRef.current = provider;

      if (isNewProvider) {
        // Set up event listeners to track state
        provider.on("status", (statusObj: { status: string }) => {
          const status = statusObj.status;
          console.log("useCollaboration: Provider status changed:", status);
          if (status === "connected") {
            setConnectionStatus("connected");
          } else if (status === "connecting") {
            setConnectionStatus("connecting");
          } else if (status === "disconnected") {
            setConnectionStatus("disconnected");
          }
        });

        provider.on("sync", (synced: boolean) => {
          console.log("useCollaboration: Provider sync event:", synced);
          setIsSynced(synced);
          if (synced) {
            onSyncedRef.current?.();
          }
        });

        // Listen for collaborator changes
        provider.onCollaborators((newCollaborators) => {
          console.log("useCollaboration: Collaborators updated:", newCollaborators.length);
          setCollaborators(newCollaborators);
        });
      } else {
        // For an existing provider, sync current state to React
        // Use providerRef.current which we know is non-null here
        setCollaborators(providerRef.current!.collaborators);
      }

      return provider;
    };
  }, [wsUrl, documentId]);

  // Reset state when documentId changes or collaboration is disabled
  useEffect(() => {
    if (!isReady) {
      setConnectionStatus("disconnected");
      setIsSynced(false);
      setCollaborators([]);
    }
  }, [isReady]);

  // Cleanup on unmount - use disconnect (debounced) instead of destroy
  // This allows the provider to be reused if the component remounts quickly (React Strict Mode)
  // The provider will only be destroyed when the document ID changes (via the wsUrl change effect)
  useEffect(() => {
    return () => {
      console.log("useCollaboration: Cleaning up - disconnecting provider");
      providerRef.current?.disconnect();
      // Don't null refs - provider may be reused on quick remount
    };
  }, []);

  const connect = useCallback(() => {
    providerRef.current?.connect();
  }, []);

  const disconnect = useCallback(() => {
    providerRef.current?.disconnect();
  }, []);

  const isCollaborating = connectionStatus === "connected" && isSynced;

  // Debug log on every render
  console.log("useCollaboration RENDER:", {
    connectionStatus,
    isSynced,
    isCollaborating,
    isReady,
    hasProviderFactory: !!providerFactory,
    hasProvider: !!providerRef.current,
  });

  return useMemo(
    () => ({
      providerFactory,
      connectionStatus,
      isSynced,
      collaborators,
      isCollaborating,
      isReady,
      connect,
      disconnect,
    }),
    [
      providerFactory,
      connectionStatus,
      isSynced,
      collaborators,
      isCollaborating,
      isReady,
      connect,
      disconnect,
    ]
  );
}
