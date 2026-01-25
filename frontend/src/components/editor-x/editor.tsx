"use client";

import { useRef } from "react";
import { InitialConfigType, LexicalComposer } from "@lexical/react/LexicalComposer";
import { OnChangePlugin } from "@lexical/react/LexicalOnChangePlugin";
import { CollaborationPlugin } from "@lexical/react/LexicalCollaborationPlugin";
import { LexicalCollaboration } from "@lexical/react/LexicalCollaborationContext";
import { EditorState, SerializedEditorState } from "lexical";
import * as Y from "yjs";

import { editorTheme } from "@/components/ui/editor/themes/editor-theme";
import { TooltipProvider } from "@/components/ui/tooltip";

import { nodes } from "./nodes";
import { Plugins } from "./plugins";
import { cn } from "@/lib/utils";
import type { UserPublic } from "@/types/api";
import type { CollaborationProvider } from "@/lib/yjs/CollaborationProvider";
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

const editorConfig: InitialConfigType = {
  namespace: "Editor",
  theme: editorTheme,
  nodes,
  onError: (error: Error) => {
    console.error(error);
  },
};

export interface EditorProps {
  editorState?: EditorState;
  editorSerializedState?: SerializedEditorState;
  onChange?: (editorState: EditorState) => void;
  onSerializedChange?: (editorSerializedState: SerializedEditorState) => void;
  readOnly?: boolean;
  showToolbar?: boolean;
  className?: string;
  mentionableUsers?: UserPublic[];
  documentName?: string;
  // Collaboration props
  collaborative?: boolean;
  /**
   * Factory function for creating the collaboration provider.
   * Passed to Lexical's CollaborationPlugin.
   */
  providerFactory?: ((id: string, yjsDocMap: Map<string, Y.Doc>) => CollaborationProvider) | null;
  /**
   * Whether to track changes via OnChangePlugin.
   * Set to true when not actively collaborating to enable autosave.
   * Defaults to true when not in collaborative mode.
   */
  trackChanges?: boolean;
}

export function Editor({
  editorState,
  editorSerializedState,
  onChange,
  onSerializedChange,
  readOnly = false,
  showToolbar = true,
  className,
  mentionableUsers = [],
  documentName,
  collaborative = false,
  providerFactory,
  trackChanges,
}: EditorProps) {
  const { user } = useAuth();
  const userColor = useRef(getRandomColor());
  const userName = user?.full_name || user?.email || "Anonymous";
  // Ref for the collaboration cursors container - must be inside the scrolling editor content
  const cursorsContainerRef = useRef<HTMLDivElement>(null!);

  // Collaborative mode is active when we have a provider factory
  const useCollaborativeMode = Boolean(collaborative && providerFactory);

  // When in collaborative mode, we must set editorState to null
  // and let CollaborationPlugin manage the state
  const initialEditorState = useCollaborativeMode
    ? null
    : editorState
      ? editorState
      : editorSerializedState
        ? JSON.stringify(editorSerializedState)
        : undefined;

  // Initial editor state for bootstrapping when Yjs is empty
  // Must be a string (not a function returning string) for CollaborationPlugin
  const initialEditorStateForCollab =
    useCollaborativeMode && editorSerializedState
      ? JSON.stringify(editorSerializedState)
      : undefined;

  return (
    <div className={cn("bg-background overflow-y-auto rounded-lg border shadow", className)}>
      <LexicalComposer
        initialConfig={{
          ...editorConfig,
          editable: !readOnly,
          // In collaborative mode, editorState must be null
          // CollaborationPlugin will handle initialization
          editorState: initialEditorState,
        }}
      >
        <TooltipProvider>
          <Plugins
            showToolbar={showToolbar}
            readOnly={readOnly}
            mentionableUsers={mentionableUsers}
            documentName={documentName}
            collaborative={useCollaborativeMode}
            cursorsContainerRef={cursorsContainerRef}
          />

          {/* Official Lexical CollaborationPlugin for real-time editing */}
          {useCollaborativeMode && providerFactory && (
            <LexicalCollaboration>
              <CollaborationPlugin
                id="main"
                providerFactory={providerFactory}
                initialEditorState={initialEditorStateForCollab}
                shouldBootstrap={true}
                username={userName}
                cursorColor={userColor.current}
                cursorsContainerRef={cursorsContainerRef}
              />
            </LexicalCollaboration>
          )}

          {/* Standard onChange - enabled when trackChanges is true or when not in collaborative mode */}
          {!readOnly && (trackChanges ?? !useCollaborativeMode) && (
            <OnChangePlugin
              ignoreSelectionChange={true}
              onChange={(editorState) => {
                onChange?.(editorState);
                onSerializedChange?.(editorState.toJSON());
              }}
            />
          )}
        </TooltipProvider>
      </LexicalComposer>
    </div>
  );
}
