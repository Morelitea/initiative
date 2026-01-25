/**
 * React hook for managing collaborative document editing sessions.
 *
 * Handles:
 * - Yjs document and provider lifecycle
 * - Connection state tracking
 * - Collaborator presence
 * - Fallback to autosave mode
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as Y from "yjs";

import { API_BASE_URL } from "@/api/client";
import { useAuth } from "./useAuth";
import { useGuilds } from "./useGuilds";
import {
  CollaborationProvider,
  CollaboratorInfo,
  ConnectionStatus,
} from "@/lib/yjs/CollaborationProvider";

export interface UseCollaborationOptions {
  documentId: number;
  enabled?: boolean;
  onSynced?: () => void;
  onError?: (error: Error) => void;
}

export interface UseCollaborationResult {
  /** The Yjs document for binding to Lexical */
  doc: Y.Doc | null;
  /** The collaboration provider instance */
  provider: CollaborationProvider | null;
  /** Current connection status */
  connectionStatus: ConnectionStatus;
  /** Whether the initial sync is complete */
  isSynced: boolean;
  /** List of current collaborators */
  collaborators: CollaboratorInfo[];
  /** Whether collaboration is active (connected and synced) */
  isCollaborating: boolean;
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

  // Use refs to maintain stable references across renders
  const docRef = useRef<Y.Doc | null>(null);
  const providerRef = useRef<CollaborationProvider | null>(null);

  // Create stable callback refs
  const onSyncedRef = useRef(onSynced);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onSyncedRef.current = onSynced;
    onErrorRef.current = onError;
  }, [onSynced, onError]);

  // Initialize Yjs document
  useEffect(() => {
    if (!docRef.current) {
      docRef.current = new Y.Doc();
    }

    return () => {
      // Clean up on unmount
      if (docRef.current) {
        docRef.current.destroy();
        docRef.current = null;
      }
    };
  }, []);

  // Initialize provider and manage connection
  useEffect(() => {
    if (!enabled || !token || !activeGuildId || !documentId || !docRef.current) {
      // Clean up existing provider
      if (providerRef.current) {
        providerRef.current.destroy();
        providerRef.current = null;
      }
      setConnectionStatus("disconnected");
      setIsSynced(false);
      setCollaborators([]);
      return;
    }

    const doc = docRef.current;

    // Create new provider
    const provider = new CollaborationProvider(doc, {
      documentId,
      guildId: activeGuildId,
      token,
      baseUrl: API_BASE_URL,
      onSynced: () => {
        setIsSynced(true);
        onSyncedRef.current?.();
      },
      onDisconnected: () => {
        // Handled by connection status change
      },
      onCollaboratorsChange: (newCollaborators) => {
        setCollaborators(newCollaborators);
      },
      onConnectionStatusChange: (status) => {
        setConnectionStatus(status);
        if (status === "error") {
          onErrorRef.current?.(new Error("Collaboration connection failed"));
        }
      },
    });

    providerRef.current = provider;

    // Connect
    provider.connect();

    return () => {
      provider.destroy();
      providerRef.current = null;
    };
  }, [enabled, token, activeGuildId, documentId]);

  const connect = useCallback(() => {
    providerRef.current?.connect();
  }, []);

  const disconnect = useCallback(() => {
    providerRef.current?.disconnect();
  }, []);

  const isCollaborating = connectionStatus === "connected" && isSynced;

  return useMemo(
    () => ({
      doc: docRef.current,
      provider: providerRef.current,
      connectionStatus,
      isSynced,
      collaborators,
      isCollaborating,
      connect,
      disconnect,
    }),
    [connectionStatus, isSynced, collaborators, isCollaborating, connect, disconnect]
  );
}
