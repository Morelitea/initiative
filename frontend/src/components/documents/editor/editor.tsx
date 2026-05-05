"use client";

import { useMemo, useRef } from "react";
import { CodeExtension } from "@lexical/code";
import { CodePrismExtension } from "@lexical/code-prism";
import {
  AutoFocusExtension,
  ClearEditorExtension,
  DecoratorTextExtension,
  HorizontalRuleExtension,
  SelectionAlwaysOnDisplayExtension,
} from "@lexical/extension";
import { HashtagExtension } from "@lexical/hashtag";
import { HistoryExtension } from "@lexical/history";
import {
  AutoLinkExtension,
  ClickableLinkExtension,
  createLinkMatcherWithRegExp,
  LinkExtension,
} from "@lexical/link";
import { CheckListExtension, ListExtension } from "@lexical/list";
import { OverflowNode } from "@lexical/overflow";
import { LexicalCollaboration } from "@lexical/react/LexicalCollaborationContext";
import { CollaborationPlugin } from "@lexical/react/LexicalCollaborationPlugin";
import { LexicalExtensionComposer } from "@lexical/react/LexicalExtensionComposer";
import { OnChangePlugin } from "@lexical/react/LexicalOnChangePlugin";
import { RichTextExtension } from "@lexical/rich-text";
import { TableCellNode, TableNode, TableRowNode } from "@lexical/table";
import {
  configExtension,
  defineExtension,
  type EditorState,
  type SerializedEditorState,
} from "lexical";
import * as Y from "yjs";

import { Loader2 } from "lucide-react";

import { editorTheme } from "@/components/ui/editor/themes/editor-theme";
import { TooltipProvider } from "@/components/ui/tooltip";

import { EmbedNode } from "@/components/ui/editor/nodes/embed-node";
import { TweetNode } from "@/components/ui/editor/nodes/embeds/tweet-node";
import { YouTubeNode } from "@/components/ui/editor/nodes/embeds/youtube-node";
import { MentionNode } from "@/components/ui/editor/nodes/mention-node";
import { WikilinkNode } from "@/components/ui/editor/nodes/wikilink-node";

import { EmojisExtension } from "@/components/ui/editor/extensions/emojis-extension";
import { HeadingAnchorExtension } from "@/components/ui/editor/extensions/heading-anchor-extension";
import { ImagesExtension } from "@/components/ui/editor/extensions/images-extension";
import { KeywordsExtension } from "@/components/ui/editor/extensions/keywords-extension";
import { LayoutExtension } from "@/components/ui/editor/extensions/layout-extension";
import { ListMaxIndentLevelExtension } from "@/components/ui/editor/extensions/list-max-indent-level-extension";
import { MarkdownShortcutsExtension } from "@/components/ui/editor/extensions/markdown-shortcuts-extension";

import { validateUrl } from "@/components/ui/editor/utils/url";
import { Plugins } from "./plugins";
import { cn } from "@/lib/utils";
import type { UserPublic } from "@/api/generated/initiativeAPI.schemas";
import type { CollaborationProvider } from "@/lib/yjs/CollaborationProvider";
import { useAuth } from "@/hooks/useAuth";
import { getUserColorHsl } from "@/lib/userColor";

const URL_REGEX =
  /((https?:\/\/(www\.)?)|(www\.))[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_+.~#?&//=]*)(?<![-.+():%])/;

const EMAIL_REGEX =
  /(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))/;

const AUTO_LINK_MATCHERS = [
  createLinkMatcherWithRegExp(URL_REGEX, (text) =>
    text.startsWith("http") ? text : `https://${text}`
  ),
  createLinkMatcherWithRegExp(EMAIL_REGEX, (text) => `mailto:${text}`),
];

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
  collaborative?: boolean;
  providerFactory?: ((id: string, yjsDocMap: Map<string, Y.Doc>) => CollaborationProvider) | null;
  trackChanges?: boolean;
  isSynced?: boolean;
  initiativeId?: number | null;
  onWikilinkNavigate?: (documentId: number) => void;
  onWikilinkCreate?: (title: string, onCreated: (documentId: number) => void) => void;
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
  isSynced = true,
  initiativeId = null,
  onWikilinkNavigate,
  onWikilinkCreate,
}: EditorProps) {
  const { user } = useAuth();
  const userColor = useRef(user ? getUserColorHsl(user.id) : "hsl(0, 0%, 70%)");
  const userName = user?.full_name || user?.email || "Anonymous";
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

  const appExtension = useMemo(() => {
    const wasCollaborative = initialCollabRef.current;
    const initState = initialEditorStateRef.current;
    const initSerialized = initialEditorSerializedStateRef.current;

    return defineExtension({
      name: "@initiative/document-editor",
      namespace: "Editor",
      nodes: [
        OverflowNode,
        TableNode,
        TableCellNode,
        TableRowNode,
        MentionNode,
        TweetNode,
        YouTubeNode,
        EmbedNode,
        WikilinkNode,
      ],
      theme: editorTheme,
      editable: !initialReadOnlyRef.current,
      onError: (error) => console.error(error),
      // In collaborative mode, leave the initial state empty.
      // CollaborationPlugin owns the initial state via its initialEditorState prop.
      $initialEditorState: wasCollaborative
        ? null
        : initState
          ? initState
          : initSerialized
            ? JSON.stringify(initSerialized)
            : null,
      dependencies: [
        RichTextExtension,
        AutoFocusExtension,
        SelectionAlwaysOnDisplayExtension,
        // History is owned by Yjs in collaborative mode; only register HistoryExtension otherwise.
        ...(wasCollaborative ? [] : [HistoryExtension]),
        configExtension(LinkExtension, {
          validateUrl,
          attributes: { rel: "noopener noreferrer", target: "_blank" },
        }),
        configExtension(AutoLinkExtension, { matchers: AUTO_LINK_MATCHERS }),
        ClickableLinkExtension,
        ListExtension,
        CheckListExtension,
        HorizontalRuleExtension,
        ClearEditorExtension,
        DecoratorTextExtension,
        HashtagExtension,
        CodeExtension,
        CodePrismExtension,
        EmojisExtension,
        ImagesExtension,
        KeywordsExtension,
        LayoutExtension,
        HeadingAnchorExtension,
        ListMaxIndentLevelExtension,
        MarkdownShortcutsExtension,
      ],
    });
  }, []);

  return (
    <div
      className={cn(
        "bg-background relative scroll-pb-14 overflow-y-auto rounded-lg border shadow",
        className
      )}
    >
      {showSyncingOverlay && (
        <div className="bg-background/80 absolute inset-0 z-50 flex items-center justify-center">
          <div className="text-muted-foreground flex items-center gap-2">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Syncing document...</span>
          </div>
        </div>
      )}
      <LexicalExtensionComposer extension={appExtension} contentEditable={null}>
        <TooltipProvider>
          <Plugins
            showToolbar={showToolbar}
            readOnly={readOnly}
            mentionableUsers={mentionableUsers}
            documentName={documentName}
            collaborative={useCollaborativeMode}
            cursorsContainerRef={cursorsContainerRef}
            initiativeId={initiativeId}
            onWikilinkNavigate={onWikilinkNavigate}
            onWikilinkCreate={onWikilinkCreate}
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
    </div>
  );
}
