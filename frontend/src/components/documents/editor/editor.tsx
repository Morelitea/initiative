"use client";

import { LexicalCollaboration } from "@lexical/react/LexicalCollaborationContext";
import { CollaborationPlugin } from "@lexical/react/LexicalCollaborationPlugin";
import { LexicalExtensionComposer } from "@lexical/react/LexicalExtensionComposer";
import { OnChangePlugin } from "@lexical/react/LexicalOnChangePlugin";
import type { EditorState, SerializedEditorState } from "lexical";
import { Loader2 } from "lucide-react";
import { useMemo, useRef } from "react";
import type * as Y from "yjs";

import type { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useAuth } from "@/hooks/useAuth";
import { SmartChipScope } from "@/hooks/useSmartChips";
import { getUserColorHsl } from "@/lib/userColor";
import { getUserDisplayName } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";
import type { CollaborationProvider } from "@/lib/yjs/CollaborationProvider";

import { documentExtension } from "./document-extension";
import { Plugins } from "./plugins";

export interface EditorProps {
  editorState?: EditorState;
  editorSerializedState?: SerializedEditorState;
  onChange?: (editorState: EditorState) => void;
  onSerializedChange?: (editorSerializedState: SerializedEditorState) => void;
  readOnly?: boolean;
  showToolbar?: boolean;
  className?: string;
  collaborative?: boolean;
  providerFactory?: ((id: string, yjsDocMap: Map<string, Y.Doc>) => CollaborationProvider) | null;
  trackChanges?: boolean;
  isSynced?: boolean;
  initiativeId?: number | null;
  /** Whether this document is prose — see `Plugins.supportsEntityMentions`. */
  supportsEntityMentions?: boolean;
  onWikilinkNavigate?: (documentId: number) => void;
  onCreateReferencedThing?: (
    name: string,
    onCreated: (entityType: SearchEntityType, entityId: number, name: string) => void
  ) => void;
}

export function Editor({
  editorState,
  editorSerializedState,
  onChange,
  onSerializedChange,
  readOnly = false,
  showToolbar = true,
  className,
  collaborative = false,
  providerFactory,
  trackChanges,
  isSynced = true,
  initiativeId = null,
  supportsEntityMentions = false,
  onWikilinkNavigate,
  onCreateReferencedThing,
}: EditorProps) {
  const { user } = useAuth();
  const userColor = useRef(user ? getUserColorHsl(user.id) : "hsl(0, 0%, 70%)");
  const userName = getUserDisplayName(user, "Anonymous");
  const cursorsContainerRef = useRef<HTMLDivElement>(null!);

  const useCollaborativeMode = Boolean(collaborative && providerFactory);

  const initialEditorStateForCollab =
    useCollaborativeMode && editorSerializedState
      ? JSON.stringify(editorSerializedState)
      : undefined;

  const showSyncingOverlay = useCollaborativeMode && !isSynced;

  // Capture initial editor configuration at first mount. LexicalExtensionComposer
  // recreates (and disposes) the editor whenever the `extension` prop reference
  // changes, so the AppExtension must be stable across re-renders. Subsequent
  // changes to readOnly are applied via editor.setEditable() inside Plugins;
  // editorState / editorSerializedState are only consulted by $initialEditorState
  // which runs once at editor creation, so refs are sufficient.
  const initialReadOnlyRef = useRef(readOnly);
  const initialCollabRef = useRef(useCollaborativeMode);
  const initialEditorStateRef = useRef(editorState);
  const initialEditorSerializedStateRef = useRef(editorSerializedState);

  const appExtension = useMemo(
    () =>
      documentExtension({
        collaborative: initialCollabRef.current,
        editable: !initialReadOnlyRef.current,
        initialEditorState:
          initialEditorStateRef.current ??
          (initialEditorSerializedStateRef.current
            ? JSON.stringify(initialEditorSerializedStateRef.current)
            : null),
      }),
    []
  );

  return (
    <div
      className={cn(
        "relative scroll-pb-14 overflow-y-auto rounded-lg border bg-background shadow",
        className
      )}
    >
      {showSyncingOverlay && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-background/80">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Syncing document...</span>
          </div>
        </div>
      )}
      {/* Outside the composer on purpose: chips and references render as Lexical
          decorators, which the composer portals in itself. Only something above
          it is an ancestor of all of them. */}
      <SmartChipScope>
        <LexicalExtensionComposer extension={appExtension} contentEditable={null}>
          <TooltipProvider>
            <Plugins
              showToolbar={showToolbar}
              readOnly={readOnly}
              collaborative={useCollaborativeMode}
              cursorsContainerRef={cursorsContainerRef}
              initiativeId={initiativeId}
              supportsEntityMentions={supportsEntityMentions}
              onWikilinkNavigate={onWikilinkNavigate}
              onCreateReferencedThing={onCreateReferencedThing}
            />

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
        </LexicalExtensionComposer>
      </SmartChipScope>
    </div>
  );
}
