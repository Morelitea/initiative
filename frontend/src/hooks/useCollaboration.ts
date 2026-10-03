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

import { apiClient } from "@/api/client";
import { toBase64 } from "@/lib/base64";
import { buildCommunityWsUrl } from "@/lib/wsUrl";
import {
  type CollaborationProvider,
  type CollaboratorInfo,
  getLiveProvider,
  getOrCreateProvider,
} from "@/lib/yjs/CollaborationProvider";

import { useAuth } from "./useAuth";
import { useCommunities } from "./useCommunities";

export type ConnectionStatus = "disconnected" | "connecting" | "connected" | "error";

/** Browsers refuse a keepalive request whose body is past 64 KiB. */
const KEEPALIVE_LIMIT = 60_000;

export interface UseCollaborationOptions {
  /**
   * The room, as the server addresses it: the collaboration path under
   * `/c/{communityId}/collaboration/`. A document is
   * `documents/{id}/collaborate`; a wiki page is
   * `wiki-pages/{id}/collaborate`.
   *
   * The path IS the identity — changing it is what tears the old socket down
   * and opens the new one — so nothing else needs to say which body this is.
   * `null` while the caller does not know yet, which keeps the hook idle.
   */
  socketPath: string | null;
  enabled?: boolean;
  onSynced?: () => void;
  onError?: (error: Error) => void;
}

export interface UseCollaborationResult {
  /**
   * Factory function for Lexical's CollaborationPlugin.
   * Returns null if collaboration is not ready (missing auth, community, etc.)
   */
  providerFactory: ((id: string, yjsDocMap: Map<string, Y.Doc>) => CollaborationProvider) | null;
  /** Current connection status */
  connectionStatus: ConnectionStatus;
  /** Whether the room and this client agree right now. False again while a
   *  dropped socket reconnects. */
  isSynced: boolean;
  /** Whether this body has synced with its room at least once. What a
   *  "syncing" cover waits on: after the first sync the editor already holds
   *  the document, and what is written during a reconnect is handed over when
   *  the socket is back. */
  hasSynced: boolean;
  /** List of current collaborators */
  collaborators: CollaboratorInfo[];
  /** Whether the server's collaborator roster has been received for this
   *  session. The roster arrives on the socket right after the initial
   *  sync, so consumers that branch on "is anyone else here?" (e.g. the
   *  whiteboard bootstrap) must wait for this — at the moment `isSynced`
   *  flips true, `collaborators` is still the empty initial state. */
  collaboratorsReady: boolean;
  /** Whether collaboration is active (connected and synced) */
  isCollaborating: boolean;
  /** Whether the hook is ready to provide collaboration */
  isReady: boolean;
  /** Start the connection over with a fresh retry budget — what to call when
   *  the network is back and the socket should stop waiting out its backoff. */
  resume: () => void;
}

export function useCollaboration({
  socketPath,
  enabled = true,
  onSynced,
  onError,
}: UseCollaborationOptions): UseCollaborationResult {
  const { user } = useAuth();
  const { activeCommunityId } = useCommunities();

  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("disconnected");
  const [isSynced, setIsSynced] = useState(false);
  const [hasSynced, setHasSynced] = useState(false);
  const [collaborators, setCollaborators] = useState<CollaboratorInfo[]>([]);
  const [collaboratorsReady, setCollaboratorsReady] = useState(false);

  // Store the provider reference so we can track its state
  const providerRef = useRef<CollaborationProvider | null>(null);
  // Track the current WebSocket URL to detect when it changes
  const currentWsUrlRef = useRef<string | null>(null);
  // Sync timeout to detect stuck connections
  const syncTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Where edits made without a socket are handed over: the room's own path.
  const handoverPathRef = useRef<string | null>(null);

  // Create stable callback refs. Allow undefined so we can clear them in the
  // unmount cleanup — otherwise an in-flight reconnect that resolves after
  // unmount could still call them, and a toast would fire on a page the user
  // has already left.
  const onSyncedRef = useRef<UseCollaborationOptions["onSynced"]>(onSynced);
  const onErrorRef = useRef<UseCollaborationOptions["onError"]>(onError);
  useEffect(() => {
    onSyncedRef.current = onSynced;
    onErrorRef.current = onError;
  }, [onSynced, onError]);

  // Check if we have all required values
  const isReady = Boolean(enabled && user && activeCommunityId && socketPath);

  // Build the WebSocket URL (memoized to detect changes). The credential
  // rides in the socket's first frame, never the URL; the community is the
  // /c/{communityId} path segment.
  const wsUrl = useMemo(() => {
    if (!isReady || !activeCommunityId) {
      return null;
    }
    return buildCommunityWsUrl(activeCommunityId, `collaboration/${socketPath}`);
  }, [isReady, activeCommunityId, socketPath]);

  // Hand the room anything this tab has that it has not seen, as the page is
  // hidden or left while the socket is gone: the edits made meanwhile, as a
  // keepalive request that outlives the page, merged into the room there.
  const handOver = useCallback(() => {
    const provider = providerRef.current;
    const path = handoverPathRef.current;
    if (!provider || !path || provider.connected) return;
    const unsent = provider.unsentEdits();
    if (!unsent) return;
    const body = JSON.stringify({ update: toBase64(unsent.update) });
    apiClient
      .post(path, body, {
        headers: { "Content-Type": "application/json" },
        adapter: "fetch",
        fetchOptions: { keepalive: body.length <= KEEPALIVE_LIMIT },
      })
      .then(() => provider.handedOver(unsent.stateVector))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const onHidden = () => {
      if (document.visibilityState === "hidden") handOver();
    };
    window.addEventListener("pagehide", handOver);
    document.addEventListener("visibilitychange", onHidden);
    return () => {
      window.removeEventListener("pagehide", handOver);
      document.removeEventListener("visibilitychange", onHidden);
    };
  }, [handOver]);

  // Clean up provider when URL changes (a community change, or a move to another
  // body entirely). A renewed credential is not a change: the socket reads it
  // as it writes each first frame.
  useEffect(() => {
    if (currentWsUrlRef.current && currentWsUrlRef.current !== wsUrl) {
      handOver();
      providerRef.current?.destroy();
      providerRef.current = null;
      // Reset state when switching bodies - critical for navigation
      setConnectionStatus("disconnected");
      setIsSynced(false);
      setHasSynced(false);
      setCollaborators([]);
      setCollaboratorsReady(false);
    }
    currentWsUrlRef.current = wsUrl;
    handoverPathRef.current =
      wsUrl && activeCommunityId ? `/c/${activeCommunityId}/collaboration/${socketPath}` : null;
  }, [wsUrl, activeCommunityId, socketPath, handOver]);

  // Create the provider factory that Lexical's CollaborationPlugin will call
  const providerFactory = useMemo(() => {
    if (!wsUrl) {
      return null;
    }

    // Return the factory function that CollaborationPlugin expects
    return (id: string, yjsDocMap: Map<string, Y.Doc>): CollaborationProvider => {
      // Check if we already have a provider with the same URL
      if (providerRef.current && currentWsUrlRef.current === wsUrl) {
        // Ensure the existing provider's Y.Doc is registered in this yjsDocMap.
        // CollaborationPlugin reads `yjsDocMap.get(id)` immediately after the
        // factory returns to seed createBinding's `doc` arg; under
        // LexicalExtensionComposer the docMap can be a fresh instance on each
        // mount, so we always have to repopulate it here.
        yjsDocMap.set(id, providerRef.current.doc);
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
      setHasSynced(false);
      setCollaborators([]);
      setCollaboratorsReady(false);

      // Update the URL ref BEFORE creating the provider
      // This prevents the wsUrl effect from destroying the new provider
      currentWsUrlRef.current = wsUrl;

      // Join a connection already in progress rather than replacing it.
      //
      // Lexical hands this factory a fresh `yjsDocMap` on every mount, so the
      // doc is new each time even when the address is not. Building another
      // one here and passing it down makes `getOrCreateProvider` destroy the
      // provider holding the live socket — and a socket destroyed before its
      // handshake finishes never syncs, which is what a remount (React's
      // development double-mount included) used to cause.
      //
      // So if a provider for this address is still alive, its doc is the one
      // the server is answering, and it is the one to use.
      const live = getLiveProvider(wsUrl);
      let doc = live?.doc ?? yjsDocMap.get(id);
      if (doc === undefined) {
        doc = new Y.Doc();
      }
      yjsDocMap.set(id, doc);

      // Reuse the provider already serving this address and doc, or open one.
      const provider = getOrCreateProvider(wsUrl, doc, { connect: true });

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
            // Start sync timeout - if we don't sync within 5s, emit error
            if (syncTimeoutRef.current) {
              clearTimeout(syncTimeoutRef.current);
            }
            syncTimeoutRef.current = setTimeout(() => {
              if (providerRef.current && !providerRef.current.synced) {
                syncTimeoutRef.current = null;
                setConnectionStatus("error");
                onErrorRef.current?.(new Error("Sync timeout - document failed to load"));
              }
            }, 5000);
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
          setCollaboratorsReady(true);
        });
      } else {
        // For an existing provider, sync current state to React
        // This is critical after quick navigation where React state resets but provider is reused
        const currentProvider = providerRef.current!;
        setCollaborators(currentProvider.collaborators);
        setCollaboratorsReady(currentProvider.collaborators.length > 0);
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
  }, [wsUrl]);

  // Reset state when the room changes or collaboration is disabled
  useEffect(() => {
    if (!isReady) {
      setConnectionStatus("disconnected");
      setIsSynced(false);
      setHasSynced(false);
      setCollaborators([]);
      setCollaboratorsReady(false);
    }
  }, [isReady]);

  // Cleanup on unmount — destroy the provider so it leaves the global
  // activeProviders map, closes the socket immediately, and stops any
  // reconnect loop. Using a soft disconnect() here was a Strict-Mode
  // optimization but caused two real bugs on real navigation: other users
  // saw the avatar flicker (provider stayed alive briefly and re-stabilized),
  // and the error callback fired toasts on pages the user had already left.
  // The Strict-Mode cost is just one extra WS setup in dev — acceptable.
  useEffect(() => {
    return () => {
      // Whatever the room lacks goes to it before the socket closes.
      handOver();
      providerRef.current?.destroy();
      providerRef.current = null;
      currentWsUrlRef.current = null;
      if (syncTimeoutRef.current) {
        clearTimeout(syncTimeoutRef.current);
        syncTimeoutRef.current = null;
      }
      // Null callback refs so any stray async invocation after destroy is a no-op.
      onSyncedRef.current = undefined;
      onErrorRef.current = undefined;
    };
  }, [handOver]);

  const resume = useCallback(() => {
    providerRef.current?.resume();
  }, []);

  // Sticky until the room changes: set from the one place that learns of a
  // sync, whichever path the provider took to get there.
  useEffect(() => {
    if (isSynced) setHasSynced(true);
  }, [isSynced]);

  const isCollaborating = connectionStatus === "connected" && isSynced;

  return useMemo(
    () => ({
      providerFactory,
      connectionStatus,
      isSynced,
      hasSynced,
      collaborators,
      collaboratorsReady,
      isCollaborating,
      isReady,
      resume,
    }),
    [
      providerFactory,
      connectionStatus,
      isSynced,
      hasSynced,
      collaborators,
      collaboratorsReady,
      isCollaborating,
      isReady,
      resume,
    ]
  );
}
