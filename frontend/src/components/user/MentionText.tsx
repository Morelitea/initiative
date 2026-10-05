import type { ReactNode } from "react";

import { UserMention } from "@/components/user/UserMention";
import { USER_MENTION_PATTERN } from "@/lib/commentReferences";

interface MentionTextProps {
  /** Plain words that may mention people, `@[](42)`. */
  text: string;
  /** The community the text was written in, where a list spans several. */
  communityId?: number;
  /** Render the people as plain words — see `UserHoverLink`. */
  disableLink?: boolean;
}

/**
 * A line of plain text with the people it mentions drawn as chips.
 *
 * For the one-line excerpts a list row shows, which the server cuts down to
 * words and the mentions in them, so that a person is named as they are called
 * now. It is not read as markdown: what is left is words, and parsing them
 * again would read meaning into a stray `*`. The list it sits in resolves the
 * people (`MentionedPeopleScope`).
 */
export const MentionText = ({ text, communityId, disableLink }: MentionTextProps) => {
  const parts: ReactNode[] = [];
  let end = 0;
  for (const match of text.matchAll(USER_MENTION_PATTERN)) {
    const [written, label, id] = match;
    parts.push(
      text.slice(end, match.index),
      <UserMention
        key={match.index}
        userId={Number(id)}
        fallback={label}
        communityId={communityId}
        disableLink={disableLink}
      />
    );
    end = match.index + written.length;
  }
  parts.push(text.slice(end));
  return <>{parts}</>;
};
