/**
 * Lexical plugin for Yjs collaborative editing integration.
 *
 * This plugin uses @lexical/yjs low-level API to create a binding
 * between Lexical and our custom Yjs provider.
 */

import { useEffect, useRef } from "react";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import {
  createBinding,
  syncLexicalUpdateToYjs,
  syncYjsChangesToLexical,
  initLocalState,
  type Binding,
  type Provider,
} from "@lexical/yjs";
// Note: We intentionally don't import Lexical node helpers here
// The sync functions handle all node operations internally
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
 * Creates a Lexical-compatible Provider wrapper from our custom CollaborationProvider.
 */
function createProviderWrapper(customProvider: CustomProvider): Provider {
  const awareness = customProvider.getAwareness();

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
      // Already connected
    },
    disconnect: () => {
      // Handled by useCollaboration cleanup
    },
    on: (type: string, cb: (...args: unknown[]) => void) => {
      if (type === "sync") {
        // Already synced when we get here
        if (customProvider.isSynced()) {
          (cb as (isSynced: boolean) => void)(true);
        }
      } else if (type === "status") {
        const status = customProvider.getConnectionStatus();
        (cb as (arg0: { status: string }) => void)({ status });
      }
      // We don't need to track these callbacks since we handle updates directly
    },
    off: () => {
      // Cleanup handled elsewhere
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
 * Uses @lexical/yjs directly to create a binding between the editor
 * and the Yjs document.
 *
 * Note: When using this plugin, HistoryPlugin should be disabled
 * as Yjs provides its own undo/redo functionality.
 */
export function CollaborationPlugin({ doc, provider, isConnected }: CollaborationPluginProps) {
  const [editor] = useLexicalComposerContext();
  const { user } = useAuth();
  const userColor = useRef(getRandomColor());
  const bindingRef = useRef<Binding | null>(null);

  const userName = user?.full_name || user?.email || "Anonymous";

  useEffect(() => {
    if (!isConnected || !doc || !provider) {
      console.log("CollaborationPlugin: Not ready, waiting for connection");
      return;
    }

    console.log("CollaborationPlugin: Setting up binding");
    console.log("  - doc clientID:", doc.clientID);
    console.log("  - userName:", userName);

    // Create the provider wrapper
    const providerWrapper = createProviderWrapper(provider);

    // Create the binding between Lexical and Yjs
    // The binding will create/use a shared XmlText named 'root' in the doc
    const binding = createBinding(
      editor,
      providerWrapper,
      "root", // ID for the shared type
      doc,
      new Map([[doc.clientID.toString(), doc]]) // Document map
    );

    bindingRef.current = binding;

    // Initialize local awareness state
    initLocalState(providerWrapper, userName, userColor.current, true, {});

    // Get the shared root from the binding's root CollabElementNode
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const sharedRoot = (binding.root as any)._xmlText as Y.XmlElement;
    console.log(
      "CollaborationPlugin: sharedRoot type:",
      sharedRoot?.constructor?.name,
      "length:",
      sharedRoot?.length
    );

    // Always do a full Yjs -> Lexical sync first
    // If Yjs has content, this populates Lexical from it
    // If Yjs is empty, this ensures the binding is in a consistent state
    const hasYjsContent = sharedRoot && sharedRoot.length > 0;
    console.log(
      "CollaborationPlugin: hasYjsContent:",
      hasYjsContent,
      "sharedRoot length:",
      sharedRoot?.length
    );

    // Sync Yjs state to Lexical (initializes the collab node tree)
    editor.update(
      () => {
        syncYjsChangesToLexical(binding, providerWrapper, [], true);
      },
      { tag: "collaboration" }
    );
    console.log("CollaborationPlugin: Initial sync complete");

    // Now set up Lexical -> Yjs sync for incremental changes
    const removeUpdateListener = editor.registerUpdateListener(
      ({ editorState, dirtyElements, dirtyLeaves, prevEditorState, tags }) => {
        // Skip if this is a collaboration update (to avoid loops)
        if (tags.has("collaboration") || tags.has("historic")) {
          return;
        }

        if (dirtyElements.size === 0 && dirtyLeaves.size === 0) {
          return;
        }

        console.log(
          "CollaborationPlugin: Syncing Lexical -> Yjs, dirty:",
          dirtyElements.size,
          "elements,",
          dirtyLeaves.size,
          "leaves"
        );

        doc.transact(() => {
          syncLexicalUpdateToYjs(
            binding,
            providerWrapper,
            prevEditorState,
            editorState,
            dirtyElements,
            dirtyLeaves,
            new Set(), // normalizedNodes
            tags
          );
        }, binding);
      }
    );

    // Set up Yjs -> Lexical sync using doc update event
    const onDocUpdate = (update: Uint8Array, origin: unknown) => {
      // Skip our own changes (from Lexical -> Yjs sync)
      if (origin === binding) {
        return;
      }

      console.log(
        "CollaborationPlugin: Remote doc update, origin:",
        origin,
        "update size:",
        update.length
      );

      // Do a full Yjs -> Lexical sync for remote updates
      editor.update(
        () => {
          syncYjsChangesToLexical(binding, providerWrapper, [], true);
        },
        { tag: "collaboration" }
      );
    };

    doc.on("update", onDocUpdate);

    console.log("CollaborationPlugin: Binding ready");

    return () => {
      console.log("CollaborationPlugin: Cleaning up binding");
      removeUpdateListener();
      doc.off("update", onDocUpdate);
    };
  }, [editor, doc, provider, isConnected, userName]);

  // This plugin doesn't render anything
  return null;
}
