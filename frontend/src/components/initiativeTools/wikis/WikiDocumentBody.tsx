import { Loader2 } from "lucide-react";
import { Suspense, useMemo } from "react";

import type { DocumentRead } from "@/api/generated/initiativeAPI.schemas";
import { DOCUMENT_BODIES } from "@/components/documents/detail/documentBodies";
import { useCollaboration } from "@/hooks/useCollaboration";

const ignore = () => {};

/** Whether a document reads best across the wiki's wide column: everything
 * that is not written prose. */
export const isWideDocument = (document: DocumentRead | undefined) =>
  document !== undefined && !DOCUMENT_BODIES[document.document_type].prose;

/**
 * A document in a wiki, drawn by the body its own page draws it with — a file
 * in its viewer, a whiteboard on its canvas, a spreadsheet in its grid — and
 * never edited here. Writing happens at the document's own address, so the
 * body joins no room and its edits go nowhere.
 */
export const WikiDocumentBody = ({ document }: { document: DocumentRead }) => {
  // What the document page holds for a body that joins no room.
  const collaboration = useCollaboration({ socketPath: null, enabled: false });
  const { Body, saved, prose } = DOCUMENT_BODIES[document.document_type];
  const content = useMemo(() => saved(document), [saved, document]);

  return (
    <Suspense
      fallback={
        <div className="flex h-96 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      }
    >
      <Body
        key={document.id}
        document={document}
        saved={content}
        canEdit={false}
        collaboration={collaboration}
        live={false}
        settled
        title={document.name}
        // Prose runs on in the wiki's own column rather than in a card.
        className={
          prose ? "max-h-none rounded-none border-0 bg-transparent shadow-none" : undefined
        }
        compact
        onChange={ignore}
      />
    </Suspense>
  );
};
