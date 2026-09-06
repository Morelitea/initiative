import type { SerializedEditorState } from "lexical";
import { lazy, Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

// The editor is the largest thing in the bundle and a board is often the first
// page someone lands on, so it arrives on demand rather than in the route chunk.
const Editor = lazy(() =>
  import("@/components/documents/editor/editor").then((m) => ({ default: m.Editor }))
);

interface PostBodyProps {
  /** The stored Lexical state. An empty object is a post with only a headline. */
  body: Record<string, unknown>;
  className?: string;
}

const isEmpty = (body: Record<string, unknown>) => !body || Object.keys(body).length === 0;

/**
 * A post's body, rendered read-only.
 *
 * The same editor that wrote it, with editing and the toolbar off — which is
 * what keeps an image, a smart chip and a mention looking the same in the feed
 * as they did in the composer. A chip re-reads its own state here too, so a
 * notice about a task keeps showing that task's *current* column.
 */
export const PostBody = ({ body, className }: PostBodyProps) => {
  if (isEmpty(body)) return null;
  return (
    <div className={cn("text-sm", className)}>
      <Suspense fallback={<Skeleton className="h-16 w-full" />}>
        <Editor
          editorSerializedState={body as unknown as SerializedEditorState}
          readOnly
          showToolbar={false}
          variant="post"
          compact
        />
      </Suspense>
    </div>
  );
};
