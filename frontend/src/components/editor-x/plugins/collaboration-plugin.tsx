/**
 * Lexical plugin for Yjs collaborative editing integration.
 *
 * This plugin wraps Lexical's built-in CollaborationPlugin and adapts
 * our custom WebSocket provider to work with Lexical's expected interface.
 */

import { useMemo, useRef } from "react";
import { CollaborationPlugin as LexicalCollaborationPlugin } from "@lexical/react/LexicalCollaborationPlugin";
import type { Provider } from "@lexical/yjs";
import * as Y from "yjs";

import { CollaborationProvider as CustomProvider } from "@/lib/yjs/CollaborationProvider";
import { useAuth } from "@/hooks/useAuth";

// Generate a random color for cursor presence
function getRandomColor(): string {
  const colors = [
    "#f87171", // red
    "#fb923c", // orange
    "#fbbf24", // amber
    "#a3e635", // lime
    "#34d399", // emerald
    "#22d3ee", // cyan
    "#60a5fa", // blue
    "#a78bfa", // violet
    "#f472b6", // pink
  ];
  return colors[Math.floor(Math.random() * colors.length)];
}

/**
 * Creates a Lexical-compatible Provider from our custom CollaborationProvider.
 */
function createLexicalProvider(customProvider: CustomProvider, doc: Y.Doc): Provider {
  const awareness = customProvider.getAwareness();
  const syncCallbacks = new Set<(isSynced: boolean) => void>();
  const updateCallbacks = new Set<(arg0: unknown) => void>();
  const statusCallbacks = new Set<(arg0: { status: string }) => void>();

  // Notify sync callbacks when synced
  if (customProvider.isSynced()) {
    setTimeout(() => {
      syncCallbacks.forEach((cb) => cb(true));
    }, 0);
  }

  // Listen for doc updates and notify callbacks
  const handleDocUpdate = (update: Uint8Array, origin: unknown) => {
    updateCallbacks.forEach((cb) => cb({ update, origin }));
  };
  doc.on("update", handleDocUpdate);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const provider: any = {
    awareness: {
      getLocalState: () => awareness.getLocalState(),
      getStates: () => awareness.getStates(),
      setLocalState: (state: Record<string, unknown> | null) => {
        if (state) {
          Object.entries(state).forEach(([key, value]) => {
            awareness.setLocalStateField(key, value);
          });
        }
      },
      setLocalStateField: (field: string, value: unknown) =>
        awareness.setLocalStateField(field, value),
      on: (type: string, cb: () => void) => {
        if (type === "update") {
          awareness.on("change", cb);
        }
      },
      off: (type: string, cb: () => void) => {
        if (type === "update") {
          awareness.off("change", cb);
        }
      },
    },
    connect: () => {
      // Already connected via useCollaboration
      if (customProvider.isSynced()) {
        syncCallbacks.forEach((cb) => cb(true));
      }
    },
    disconnect: () => {
      doc.off("update", handleDocUpdate);
    },
    on: (type: string, cb: (...args: unknown[]) => void) => {
      if (type === "sync") {
        syncCallbacks.add(cb as (isSynced: boolean) => void);
        if (customProvider.isSynced()) {
          (cb as (isSynced: boolean) => void)(true);
        }
      } else if (type === "update") {
        updateCallbacks.add(cb as (arg0: unknown) => void);
      } else if (type === "status") {
        statusCallbacks.add(cb as (arg0: { status: string }) => void);
        const status = customProvider.getConnectionStatus();
        (cb as (arg0: { status: string }) => void)({ status });
      }
    },
    off: (type: string, cb: (...args: unknown[]) => void) => {
      if (type === "sync") {
        syncCallbacks.delete(cb as (isSynced: boolean) => void);
      } else if (type === "update") {
        updateCallbacks.delete(cb as (arg0: unknown) => void);
      } else if (type === "status") {
        statusCallbacks.delete(cb as (arg0: { status: string }) => void);
      }
    },
  };

  return provider as Provider;
}

export interface CollaborationPluginProps {
  /**
   * The Yjs document from useCollaboration hook.
   */
  doc: Y.Doc;

  /**
   * The collaboration provider from useCollaboration hook.
   */
  provider: CustomProvider;

  /**
   * Whether the collaboration is fully connected and synced.
   */
  isConnected: boolean;
}

/**
 * Plugin that integrates Lexical with Yjs for collaborative editing.
 *
 * This wraps Lexical's built-in CollaborationPlugin and adapts our
 * custom WebSocket provider to work with it.
 *
 * Note: When using this plugin, HistoryPlugin should be disabled
 * as Yjs provides its own undo/redo functionality.
 */
export function CollaborationPlugin({ doc, provider, isConnected }: CollaborationPluginProps) {
  const { user } = useAuth();
  const userColor = useRef(getRandomColor());
  const lexicalProviderRef = useRef<Provider | null>(null);

  const userName = user?.full_name || user?.email || "Anonymous";

  // Create a stable provider factory that Lexical's CollaborationPlugin expects
  const providerFactory = useMemo(() => {
    return (id: string, yjsDocMap: Map<string, Y.Doc>): Provider => {
      // Store the doc in the map
      yjsDocMap.set(id, doc);

      // Create the Lexical-compatible provider
      const lexicalProvider = createLexicalProvider(provider, doc);
      lexicalProviderRef.current = lexicalProvider;

      return lexicalProvider;
    };
  }, [doc, provider]);

  // Don't render until connected
  if (!isConnected || !doc || !provider) {
    return null;
  }

  return (
    <LexicalCollaborationPlugin
      id="collab-main"
      providerFactory={providerFactory}
      shouldBootstrap={false}
      username={userName}
      cursorColor={userColor.current}
    />
  );
}
