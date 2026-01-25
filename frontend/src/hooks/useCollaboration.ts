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

  // Initialize Yjs document - create a new one for each document ID
  useEffect(() => {
    // Always create a fresh doc for each document ID to avoid state mixing
    if (docRef.current) {
      console.log("useCollaboration: Destroying previous Y.Doc for new documentId:", documentId);
      docRef.current.destroy();
    }
    const newDoc = new Y.Doc();
    docRef.current = newDoc;
    console.log(
      "useCollaboration: Created new Y.Doc, clientID:",
      newDoc.clientID,
      "for documentId:",
      documentId
    );

    return () => {
      // Clean up on unmount or when documentId changes
      if (docRef.current) {
        console.log("useCollaboration: Cleaning up Y.Doc, clientID:", docRef.current.clientID);
        docRef.current.destroy();
        docRef.current = null;
      }
    };
  }, [documentId]);

  // Initialize provider and manage connection
  useEffect(() => {
    console.log("useCollaboration: Provider effect running");
    console.log("  - enabled:", enabled);
    console.log("  - token:", token ? "present" : "missing");
    console.log("  - activeGuildId:", activeGuildId);
    console.log("  - documentId:", documentId);
    console.log(
      "  - docRef.current:",
      docRef.current ? `clientID: ${docRef.current.clientID}` : "null"
    );

    if (!enabled || !token || !activeGuildId || !documentId || !docRef.current) {
      console.log("useCollaboration: Missing required values, cleaning up");
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
    console.log(
      "useCollaboration: Creating CollaborationProvider for documentId:",
      documentId,
      "doc clientID:",
      doc.clientID
    );

    // Create new provider
    const provider = new CollaborationProvider(doc, {
      documentId,
      guildId: activeGuildId,
      token,
      baseUrl: API_BASE_URL,
      onSynced: () => {
        console.log("useCollaboration: onSynced callback fired");
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
        console.log("useCollaboration: Connection status changed to:", status);
        setConnectionStatus(status);
        if (status === "error") {
          onErrorRef.current?.(new Error("Collaboration connection failed"));
        }
      },
    });

    providerRef.current = provider;

    // Connect
    console.log("useCollaboration: Calling provider.connect()");
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

  // Debug log on every render
  console.log("useCollaboration RENDER:", {
    connectionStatus,
    isSynced,
    isCollaborating,
    hasDoc: !!docRef.current,
    hasProvider: !!providerRef.current,
  });

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
