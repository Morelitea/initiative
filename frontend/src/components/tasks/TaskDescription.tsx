import { useMemo } from "react";

import { CommentReferences } from "@/components/comments/CommentReferences";
import { Markdown } from "@/components/Markdown";

interface TaskDescriptionProps {
  content: string;
  className?: string;
}

/**
 * A task's description as it reads: markdown, with the people and things it
 * mentions shown by what they are called now rather than what they were called
 * when it was written.
 *
 * It resolves its own mentions, so mount it where one description is on
 * screen. A board of cards renders `<Markdown mentions>` instead, which shows
 * the names as written rather than asking about every card.
 */
export const TaskDescription = ({ content, className }: TaskDescriptionProps) => {
  const contents = useMemo(() => [content], [content]);
  return (
    <CommentReferences contents={contents}>
      <Markdown content={content} className={className} mentions />
    </CommentReferences>
  );
};
