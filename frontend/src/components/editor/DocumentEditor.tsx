import { useEffect, useMemo } from "react";
import { LexicalComposer, type InitialConfigType } from "@lexical/react/LexicalComposer";
import { RichTextPlugin } from "@lexical/react/LexicalRichTextPlugin";
import { HistoryPlugin } from "@lexical/react/LexicalHistoryPlugin";
import { ListPlugin } from "@lexical/react/LexicalListPlugin";
import { CheckListPlugin } from "@lexical/react/LexicalCheckListPlugin";
import { LinkPlugin } from "@lexical/react/LexicalLinkPlugin";
import { ContentEditable } from "@lexical/react/LexicalContentEditable";
import { OnChangePlugin } from "@lexical/react/LexicalOnChangePlugin";
import { LexicalErrorBoundary } from "@lexical/react/LexicalErrorBoundary";
import { HeadingNode, QuoteNode } from "@lexical/rich-text";
import { ListNode, ListItemNode } from "@lexical/list";
import { LinkNode } from "@lexical/link";
import { CodeNode } from "@lexical/code";
import { TableNode, TableCellNode, TableRowNode } from "@lexical/table";
import { HorizontalRuleNode } from "@lexical/react/LexicalHorizontalRuleNode";
import { HorizontalRulePlugin } from "@lexical/react/LexicalHorizontalRulePlugin";
import type { EditorThemeClasses, SerializedEditorState, SerializedLexicalNode } from "lexical";
import {
  CLICK_COMMAND,
  COMMAND_PRIORITY_LOW,
  INDENT_CONTENT_COMMAND,
  KEY_DOWN_COMMAND,
  KEY_TAB_COMMAND,
  OUTDENT_CONTENT_COMMAND,
  SELECT_ALL_COMMAND,
} from "lexical";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";

import { cn } from "@/lib/utils";
import { EditorToolbar } from "@/components/editor/EditorToolbar";
import { TablePlugin } from "@lexical/react/LexicalTablePlugin";
import { ImageUploadPlugin } from "@/components/editor/ImageUploadPlugin";
import { ImageNode } from "@/components/editor/nodes/ImageNode";
import { EmbedNode } from "@/components/editor/nodes/EmbedNode";

const AltClickLinkPlugin = () => {
  const [editor] = useLexicalComposerContext();

  useEffect(() => {
    return editor.registerCommand<MouseEvent>(
      CLICK_COMMAND,
      (event) => {
        if (!event.altKey) {
          return false;
        }
        const target = event.target;
        if (!(target instanceof HTMLElement)) {
          return false;
        }
        const anchor = target.closest("a");
        if (anchor && anchor.href) {
          window.open(anchor.href, "_blank", "noopener,noreferrer");
          return true;
        }
        return false;
      },
      COMMAND_PRIORITY_LOW
    );
  }, [editor]);

  return null;
};

const DocumentShortcutsPlugin = () => {
  const [editor] = useLexicalComposerContext();

  useEffect(() => {
    const unregisterSelectAll = editor.registerCommand(
      KEY_DOWN_COMMAND,
      (event) => {
        if (event.key.toLowerCase() === "a" && (event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          editor.dispatchCommand(SELECT_ALL_COMMAND, undefined as never);
          return true;
        }
        return false;
      },
      COMMAND_PRIORITY_LOW
    );

    const unregisterTab = editor.registerCommand(
      KEY_TAB_COMMAND,
      (event) => {
        if (!editor.isEditable()) {
          return false;
        }
        event?.preventDefault?.();
        editor.dispatchCommand(
          event?.shiftKey ? OUTDENT_CONTENT_COMMAND : INDENT_CONTENT_COMMAND,
          undefined as never
        );
        return true;
      },
      COMMAND_PRIORITY_LOW
    );

    return () => {
      unregisterSelectAll();
      unregisterTab();
    };
  }, [editor]);

  return null;
};

const createEmptyParagraphNode = (): SerializedLexicalNode =>
  ({
    children: [],
    direction: null,
    format: "",
    indent: 0,
    type: "paragraph",
    version: 1,
  }) as SerializedLexicalNode;

export const createEmptyEditorState = (): SerializedEditorState => ({
  root: {
    children: [createEmptyParagraphNode()],
    direction: null,
    format: "",
    indent: 0,
    type: "root",
    version: 1,
  } as SerializedEditorState["root"],
});

export const EMPTY_EDITOR_STATE: SerializedEditorState = createEmptyEditorState();

export const normalizeEditorState = (
  state?: SerializedEditorState | null
): SerializedEditorState => {
  const base =
    state && typeof state === "object"
      ? (state as SerializedEditorState)
      : createEmptyEditorState();
  const cloned = JSON.parse(JSON.stringify(base)) as SerializedEditorState;
  if (!Array.isArray(cloned.root.children) || cloned.root.children.length === 0) {
    cloned.root.children = [createEmptyParagraphNode()];
  }
  return cloned;
};

const editorTheme: EditorThemeClasses = {
  paragraph: "mb-3 text-base leading-7",
  text: {
    bold: "font-semibold",
    italic: "italic",
    underline: "underline",
  },
  link: "text-primary underline underline-offset-2 hover:text-primary/80 transition-colors",
  heading: {
    h1: "text-3xl font-semibold leading-tight tracking-tight mb-4 mt-2",
    h2: "text-2xl font-semibold leading-snug tracking-tight mt-6 mb-3",
    h3: "text-xl font-semibold leading-snug tracking-tight mt-4 mb-2",
  },
  list: {
    listitem: "ml-5",
    listitemChecked: "ml-5 line-through text-muted-foreground",
    listitemUnchecked: "ml-5",
    checklist: "document-editor__checklist",
    ul: "list-disc pl-2",
    ol: "list-decimal pl-2",
    nested: {
      listitem: "ml-2 list-none",
    },
  },
  quote: "border-l-4 border-border pl-4 italic text-muted-foreground",
  code: "bg-muted/70 font-mono px-1 py-0.5 rounded text-sm p-1",
  table: "w-full border-collapse border border-border text-sm",
  tableRow: "",
  tableCell: "border border-border px-2 py-1 align-top text-left bg-transparent",
  tableCellHeader: "border border-border px-2 py-1 text-left font-normal bg-transparent",
  tableSelection: "bg-primary/10",
};

type DocumentEditorProps = {
  initialState?: SerializedEditorState | null;
  onChange?: (state: SerializedEditorState) => void;
  readOnly?: boolean;
  placeholder?: string;
  className?: string;
  showToolbar?: boolean;
};

export const DocumentEditor = ({
  initialState,
  onChange,
  readOnly = false,
  placeholder = "Start writing…",
  className,
  showToolbar = !readOnly,
}: DocumentEditorProps) => {
  const sanitizedInitialState = useMemo(() => normalizeEditorState(initialState), [initialState]);
  const initialConfig = useMemo<InitialConfigType>(
    () => ({
      namespace: "initiative-document-editor",
      editorState: (editor) => {
        const serialized = JSON.stringify(sanitizedInitialState);
        const parsed = editor.parseEditorState(serialized);
        editor.setEditorState(parsed);
      },
      editable: !readOnly,
      theme: editorTheme,
      nodes: [
        HeadingNode,
        QuoteNode,
        ListNode,
        ListItemNode,
        LinkNode,
        CodeNode,
        TableNode,
        TableCellNode,
        TableRowNode,
        HorizontalRuleNode,
        ImageNode,
        EmbedNode,
      ],
      onError(error) {
        // Surface lexical errors during development.
        throw error;
      },
    }),
    [sanitizedInitialState, readOnly]
  );

  return (
    <LexicalComposer initialConfig={initialConfig}>
      <div
        data-document-editor="true"
        className={cn(
          "bg-card text-card-foreground relative max-h-160 overflow-y-auto rounded-xl border shadow-sm sm:max-h-250",
          className
        )}
      >
        {showToolbar ? (
          <div className="bg-card sticky top-0 z-10 rounded-t-xl border-b px-3 py-2">
            <EditorToolbar readOnly={readOnly} />
          </div>
        ) : null}
        <div className="px-4 py-3">
          <RichTextPlugin
            contentEditable={
              <ContentEditable
                className={cn(
                  "document-editor__content min-h-[260px] w-full resize-y rounded-md px-1 py-2 text-base focus:outline-none",
                  readOnly && "cursor-default"
                )}
              />
            }
            placeholder={
              <div className="text-muted-foreground pointer-events-none text-sm select-none">
                {placeholder}
              </div>
            }
            ErrorBoundary={LexicalErrorBoundary}
          />
          <HistoryPlugin />
          <ListPlugin />
          <CheckListPlugin />
          <LinkPlugin />
          <HorizontalRulePlugin />
          <AltClickLinkPlugin />
          <TablePlugin hasCellMerge hasCellBackgroundColor />
          <DocumentShortcutsPlugin />
          <ImageUploadPlugin disabled={readOnly} />
          {!readOnly ? (
            <OnChangePlugin
              onChange={(editorState) => {
                if (!onChange) {
                  return;
                }
                editorState.read(() => {
                  const normalized = normalizeEditorState(
                    editorState.toJSON() as SerializedEditorState
                  );
                  onChange(normalized);
                });
              }}
            />
          ) : null}
        </div>
      </div>
    </LexicalComposer>
  );
};

export default DocumentEditor;
