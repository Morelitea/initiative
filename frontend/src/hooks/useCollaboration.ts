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
  const { token } = useAuth();
  const { activeGuildId } = useGuilds();

  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("disconnected");
  const [isSynced, setIsSynced] = useState(false);
  const [collaborators, setCollaborators] = useState<CollaboratorInfo[]>([]);

  // Store the provider reference so we can track its state
  const providerRef = useRef<CollaborationProvider | null>(null);
  // Track the current WebSocket URL to detect when it changes
  const currentWsUrlRef = useRef<string | null>(null);
  // Sync timeout to detect stuck connections
  const syncTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
  // Token is NOT included in URL for security - sent via MSG_AUTH message instead
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
    // Note: token and guild_id are sent via MSG_AUTH message, not URL params
    return url.toString();
  }, [isReady, token, activeGuildId, documentId]);

  // Auth params to pass to the provider (sent via MSG_AUTH message)
  const authParams = useMemo(() => {
    if (!token || !activeGuildId) return null;
    return { token, guildId: activeGuildId };
  }, [token, activeGuildId]);

  // Clean up provider when URL changes (token refresh, guild change, document change, etc.)
  useEffect(() => {
    if (currentWsUrlRef.current && currentWsUrlRef.current !== wsUrl) {
      providerRef.current?.destroy();
      providerRef.current = null;
      // Reset state when switching documents - critical for navigation
      setConnectionStatus("disconnected");
      setIsSynced(false);
      setCollaborators([]);
    }
    currentWsUrlRef.current = wsUrl;
  }, [wsUrl]);

  // Create the provider factory that Lexical's CollaborationPlugin will call
  const providerFactory = useMemo(() => {
    if (!wsUrl || !authParams) {
      return null;
    }

    // Return the factory function that CollaborationPlugin expects
    return (id: string, yjsDocMap: Map<string, Y.Doc>): CollaborationProvider => {
      // Check if we already have a provider with the same URL
      if (providerRef.current && currentWsUrlRef.current === wsUrl) {
        // Ensure provider is connected (cancels pending disconnect or reconnects)
        providerRef.current.connect();
        return providerRef.current;
      }

      // Switching to a new document - destroy old provider and reset state
      if (providerRef.current) {
        providerRef.current.destroy();
        providerRef.current = null;
      }

      // Reset state for the new document
      setConnectionStatus("disconnected");
      setIsSynced(false);
      setCollaborators([]);

      // Update the URL ref BEFORE creating the provider
      // This prevents the wsUrl effect from destroying the new provider
      currentWsUrlRef.current = wsUrl;

      // Get or create the Y.Doc
      let doc = yjsDocMap.get(id);
      if (doc === undefined) {
        doc = new Y.Doc();
        yjsDocMap.set(id, doc);
      }

      // Use the factory function to get or create a provider
      // This ensures we reuse existing providers for the same document
      // Auth is sent via MSG_AUTH message after connection, not in URL
      const provider = getOrCreateProvider(wsUrl, id, doc, {
        connect: true,
        auth: authParams,
      });

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
          if (status === "connected") {
            setConnectionStatus("connected");
            // Start sync timeout - if we don't sync within 10s, emit error
            if (syncTimeoutRef.current) {
              clearTimeout(syncTimeoutRef.current);
            }
            syncTimeoutRef.current = setTimeout(() => {
              if (providerRef.current && !providerRef.current.synced) {
                syncTimeoutRef.current = null;
                setConnectionStatus("error");
                onErrorRef.current?.(new Error("Sync timeout - document failed to load"));
              }
            }, 10000);
          } else if (status === "connecting") {
            setConnectionStatus("connecting");
          } else if (status === "disconnected") {
            setConnectionStatus("disconnected");
            // Clear sync timeout - no longer expecting sync
            if (syncTimeoutRef.current) {
              clearTimeout(syncTimeoutRef.current);
              syncTimeoutRef.current = null;
            }
          } else if (status === "error") {
            setConnectionStatus("error");
            // Clear sync timeout - no longer expecting sync
            if (syncTimeoutRef.current) {
              clearTimeout(syncTimeoutRef.current);
              syncTimeoutRef.current = null;
            }
          }
        });

        provider.on("sync", (synced: boolean) => {
          setIsSynced(synced);
          if (synced) {
            // Clear sync timeout on successful sync
            if (syncTimeoutRef.current) {
              clearTimeout(syncTimeoutRef.current);
              syncTimeoutRef.current = null;
            }
            onSyncedRef.current?.();
          } else {
            // Clear timeout when sync is lost (e.g., reconnecting)
            if (syncTimeoutRef.current) {
              clearTimeout(syncTimeoutRef.current);
              syncTimeoutRef.current = null;
            }
          }
        });

        // Listen for error events
        provider.on("error", (error: Error) => {
          setConnectionStatus("error");
          // Clear sync timeout since we hit an error
          if (syncTimeoutRef.current) {
            clearTimeout(syncTimeoutRef.current);
            syncTimeoutRef.current = null;
          }
          onErrorRef.current?.(error);
        });

        // Listen for collaborator changes
        provider.onCollaborators((newCollaborators) => {
          setCollaborators(newCollaborators);
        });
      } else {
        // For an existing provider, sync current state to React
        // This is critical after quick navigation where React state resets but provider is reused
        const currentProvider = providerRef.current!;
        setCollaborators(currentProvider.collaborators);
        setIsSynced(currentProvider.synced);
        // Use the provider's tracked status instead of inferring it
        const providerStatus = currentProvider.status;
        if (
          providerStatus === "connected" ||
          providerStatus === "connecting" ||
          providerStatus === "disconnected" ||
          providerStatus === "error"
        ) {
          setConnectionStatus(providerStatus as ConnectionStatus);
        }
      }

      return provider;
    };
  }, [wsUrl, authParams]);

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
      providerRef.current?.disconnect();
      // Clear sync timeout
      if (syncTimeoutRef.current) {
        clearTimeout(syncTimeoutRef.current);
        syncTimeoutRef.current = null;
      }
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
