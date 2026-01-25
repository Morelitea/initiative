/**
 * Lexical plugin for Yjs collaborative editing integration.
 *
 * This plugin connects Lexical with our custom Yjs WebSocket provider,
 * enabling real-time collaborative editing.
 */

import { useEffect, useRef } from "react";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import * as Y from "yjs";

import { CollaborationProvider } from "@/lib/yjs/CollaborationProvider";
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

export interface CollaborationPluginProps {
  /**
   * The Yjs document from useCollaboration hook.
   */
  doc: Y.Doc;

  /**
   * The collaboration provider from useCollaboration hook.
   */
  provider: CollaborationProvider;

  /**
   * Whether the collaboration is fully connected and synced.
   */
  isConnected: boolean;
}

/**
 * Plugin that integrates Lexical with Yjs for collaborative editing.
 *
 * This is a simplified version that sets up awareness for cursor presence.
 * The actual content syncing is handled by the Yjs provider.
 *
 * Note: When using this plugin, HistoryPlugin should be disabled
 * as Yjs provides its own undo/redo functionality.
 */
export function CollaborationPlugin({ doc, provider, isConnected }: CollaborationPluginProps) {
  const [editor] = useLexicalComposerContext();
  const { user } = useAuth();
  const userColor = useRef(getRandomColor());
  const initializedRef = useRef(false);

  const userName = user?.full_name || user?.email || "Anonymous";

  useEffect(() => {
    if (!isConnected || !doc || !provider || initializedRef.current) {
      return;
    }

    // Set up awareness with user info for cursor presence
    const awareness = provider.getAwareness();
    awareness.setLocalStateField("user", {
      name: userName,
      color: userColor.current,
      colorLight: userColor.current + "33",
    });

    initializedRef.current = true;

    // Clean up on unmount
    return () => {
      initializedRef.current = false;
    };
  }, [doc, provider, isConnected, userName, editor]);

  // This plugin primarily manages awareness state
  // The actual content synchronization is handled by the Yjs provider
  return null;
}
