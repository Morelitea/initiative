import type { SerializedEditorState } from "lexical";
import { Loader2 } from "lucide-react";
import { lazy, Suspense, useMemo } from "react";

import { type DocumentRead, DocumentType } from "@/api/generated/initiativeAPI.schemas";
import type { SmartLinkContent } from "@/components/documents/SmartLinkDocumentViewer";
import type { SpreadsheetContent } from "@/components/documents/SpreadsheetDocumentEditor";
import type { WhiteboardScene } from "@/components/documents/WhiteboardDocumentEditor";

const Editor = lazy(() =>
  import("@/components/documents/editor/editor").then((m) => ({ default: m.Editor }))
);
const FileDocumentViewer = lazy(() =>
  import("@/components/documents/FileDocumentViewer").then((m) => ({
    default: m.FileDocumentViewer,
  }))
);
const SpreadsheetDocumentEditor = lazy(() =>
  import("@/components/documents/SpreadsheetDocumentEditor").then((m) => ({
    default: m.SpreadsheetDocumentEditor,
  }))
);
const WhiteboardDocumentEditor = lazy(() =>
  import("@/components/documents/WhiteboardDocumentEditor").then((m) => ({
    default: m.WhiteboardDocumentEditor,
  }))
);
const SmartLinkDocumentViewer = lazy(() =>
  import("@/components/documents/SmartLinkDocumentViewer").then((m) => ({
    default: m.SmartLinkDocumentViewer,
  }))
);

const ignore = () => {};

interface WikiDocumentBodyProps {
  document: DocumentRead;
  initiativeId: number | null;
}

/** Whether a document reads best across the wiki's wide column: everything
 * that is not written prose. */
export const isWideDocument = (document: DocumentRead | undefined) =>
  Boolean(document) && document?.document_type !== DocumentType.native;

/**
 * A document in a wiki, drawn the way its own kind is drawn — a file in its
 * viewer, a whiteboard on its canvas, a spreadsheet in its grid — and never
 * editable. Writing happens at the document's own address.
 */
export const WikiDocumentBody = ({ document, initiativeId }: WikiDocumentBodyProps) => {
  const body = useMemo(() => {
    const stored = document.content as unknown as SerializedEditorState | undefined;
    const children = stored?.root?.children;
    return Array.isArray(children) && children.length > 0 ? stored : null;
  }, [document.content]);

  const scene = useMemo<WhiteboardScene>(() => {
    const raw = (document.content ?? {}) as Partial<WhiteboardScene>;
    return { elements: raw.elements ?? [], appState: raw.appState ?? {}, files: raw.files ?? {} };
  }, [document.content]);

  return (
    <Suspense
      fallback={
        <div className="flex h-96 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      }
    >
      {document.document_type === DocumentType.file ? (
        document.file_url ? (
          <FileDocumentViewer
            documentId={document.id}
            guildId={document.guild_id}
            fileUrl={document.file_url}
            contentType={document.file_content_type}
            originalFilename={document.original_filename}
            fileSize={document.file_size}
          />
        ) : null
      ) : document.document_type === DocumentType.whiteboard ? (
        <WhiteboardDocumentEditor
          key={document.id}
          initialScene={scene}
          onSerializedChange={ignore}
          readOnly
        />
      ) : document.document_type === DocumentType.spreadsheet ? (
        <SpreadsheetDocumentEditor
          key={document.id}
          initialContent={(document.content ?? {}) as unknown as SpreadsheetContent}
          onContentChange={ignore}
          documentTitle={document.name}
          readOnly
          className="max-h-[70vh]"
        />
      ) : document.document_type === DocumentType.smart_link ? (
        <SmartLinkDocumentViewer
          key={document.id}
          content={document.content as unknown as SmartLinkContent | null}
        />
      ) : (
        <Editor
          key={document.id}
          editorSerializedState={body ?? undefined}
          readOnly
          showToolbar={false}
          className="rounded-none border-0 bg-transparent shadow-none"
          initiativeId={initiativeId}
          subject={`document:${document.id}`}
          supportsEntityMentions
          compact
        />
      )}
    </Suspense>
  );
};
