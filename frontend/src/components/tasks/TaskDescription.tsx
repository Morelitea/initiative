import { useMemo } from "react";

import { CommentReferences } from "@/components/comments/CommentReferences";
import { Markdown } from "@/components/Markdown";

interface TaskDescriptionProps {
  content: string;
  /** The community the task is in, where that is not the one the page is in. */
  guildId?: number;
  className?: string;
}

/**
 * A task's description as it reads: markdown, with the people and things it
 * mentions shown by what they are called now rather than what they were called
 * when it was written.
 *
 * It resolves its own mentions, so mount it where one description is on
 * screen. A board of cards shows each card's excerpt instead, with the people
 * in all of them asked about once for the board.
 */
export const TaskDescription = ({ content, guildId, className }: TaskDescriptionProps) => {
  const contents = useMemo(() => [content], [content]);
  return (
    <CommentReferences contents={contents} guildId={guildId}>
      <Markdown content={content} className={className} mentions />
    </CommentReferences>
  );
};
