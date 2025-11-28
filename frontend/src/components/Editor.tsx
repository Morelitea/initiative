import { useMemo } from "react";
import { LexicalComposer, type InitialConfigType } from "@lexical/react/LexicalComposer";
import { RichTextPlugin } from "@lexical/react/LexicalRichTextPlugin";
import { HistoryPlugin } from "@lexical/react/LexicalHistoryPlugin";
import { ListPlugin } from "@lexical/react/LexicalListPlugin";
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
import type { EditorThemeClasses, SerializedEditorState, SerializedLexicalNode } from "lexical";

import { cn } from "@/lib/utils";
import { EditorToolbar } from "@/components/editor/EditorToolbar";
import { TablePlugin } from "@lexical/react/LexicalTablePlugin";
import { ImageUploadPlugin } from "@/components/editor/ImageUploadPlugin";
import { ImageNode } from "@/components/editor/nodes/ImageNode";

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
  heading: {
    h1: "text-3xl font-semibold leading-tight tracking-tight mb-4 mt-2",
    h2: "text-2xl font-semibold leading-snug tracking-tight mt-6 mb-3",
    h3: "text-xl font-semibold leading-snug tracking-tight mt-4 mb-2",
  },
  list: {
    listitem: "ml-5",
    listitemChecked: "ml-5 line-through text-muted-foreground",
    listitemUnchecked: "ml-5",
    nested: {
      listitem: "ml-3",
    },
    ul: "list-disc pl-6",
    ol: "list-decimal pl-6",
  },
  code: "bg-muted/70 font-mono px-1 py-0.5 rounded text-sm p-1",
  table: "w-full border-collapse border border-border text-sm",
  tableRow: "",
  tableCell: "border border-border px-2 py-1 align-top text-left bg-transparent",
  tableCellHeader: "border border-border px-2 py-1 text-left font-normal bg-transparent",
};

type DocumentEditorProps = {
  initialState?: SerializedEditorState | null;
  onChange?: (state: SerializedEditorState) => void;
  readOnly?: boolean;
  placeholder?: string;
  className?: string;
};

export const DocumentEditor = ({
  initialState,
  onChange,
  readOnly = false,
  placeholder = "Start writing…",
  className,
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
        className={cn("rounded-xl border bg-card text-card-foreground shadow-sm", className)}
      >
        <EditorToolbar readOnly={readOnly} />
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
              <div className="pointer-events-none select-none text-sm text-muted-foreground">
                {placeholder}
              </div>
            }
            ErrorBoundary={LexicalErrorBoundary}
          />
          <HistoryPlugin />
          <ListPlugin />
          <LinkPlugin />
          <TablePlugin hasCellMerge hasCellBackgroundColor />
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
