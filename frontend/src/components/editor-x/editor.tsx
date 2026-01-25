"use client";

import { InitialConfigType, LexicalComposer } from "@lexical/react/LexicalComposer";
import { OnChangePlugin } from "@lexical/react/LexicalOnChangePlugin";
import { EditorState, SerializedEditorState } from "lexical";
import * as Y from "yjs";

import { editorTheme } from "@/components/ui/editor/themes/editor-theme";
import { TooltipProvider } from "@/components/ui/tooltip";

import { nodes } from "./nodes";
import { Plugins } from "./plugins";
import { CollaborationPlugin } from "./plugins/collaboration-plugin";
import { cn } from "@/lib/utils";
import type { UserPublic } from "@/types/api";
import type { CollaborationProvider } from "@/lib/yjs/CollaborationProvider";

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
  yjsDoc?: Y.Doc | null;
  yjsProvider?: CollaborationProvider | null;
  isCollaborating?: boolean;
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
  yjsDoc,
  yjsProvider,
  isCollaborating = false,
}: EditorProps) {
  // When collaborative mode is active and connected, we need special handling
  const useCollaborativeMode = Boolean(collaborative && isCollaborating && yjsDoc && yjsProvider);

  return (
    <div className={cn("bg-background overflow-y-auto rounded-lg border shadow", className)}>
      <LexicalComposer
        initialConfig={{
          ...editorConfig,
          editable: !readOnly,
          // When in collaborative mode, don't set initial state - Yjs handles it
          ...(useCollaborativeMode
            ? { editorState: null }
            : {
                ...(editorState ? { editorState } : {}),
                ...(editorSerializedState
                  ? { editorState: JSON.stringify(editorSerializedState) }
                  : {}),
              }),
        }}
      >
        <TooltipProvider>
          <Plugins
            showToolbar={showToolbar}
            readOnly={readOnly}
            mentionableUsers={mentionableUsers}
            documentName={documentName}
            collaborative={useCollaborativeMode}
          />

          {/* Collaboration plugin when in collaborative mode */}
          {useCollaborativeMode && yjsDoc && yjsProvider && (
            <CollaborationPlugin
              doc={yjsDoc}
              provider={yjsProvider}
              isConnected={isCollaborating}
            />
          )}

          {/* Standard onChange when not in collaborative mode */}
          {!readOnly && !useCollaborativeMode && (
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
