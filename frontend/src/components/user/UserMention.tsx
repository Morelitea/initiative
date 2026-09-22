import { UserHoverLink } from "@/components/user/UserHoverLink";
import { useMentionedPerson } from "@/hooks/useMentionedPeople";
import { getUserDisplayName } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

/** The chip itself — the same one comments and documents have always drawn. */
export const MENTION_BADGE = "rounded bg-primary/10 px-1 py-0.5 font-medium text-primary text-sm";

interface UserMentionProps {
  /** Who was named. A mention carries only this. */
  userId: number | null | undefined;
  /** The name as it read when written. What stands in until the answer
   *  arrives, and for good once they are gone. */
  fallback: string;
  /** Render as plain words — see `UserHoverLink`. */
  disableLink?: boolean;
  className?: string;
}

/**
 * Somebody named, inside prose.
 *
 * The name is read rather than stored: a comment written a year ago says what
 * that person is called today, resolved from the page's one request for
 * everyone it mentions (`MentionedPeopleScope`). Where the page has not
 * resolved them, the chip is the words it was written with and goes nowhere.
 */
export const UserMention = ({ userId, fallback, disableLink, className }: UserMentionProps) => {
  const person = useMentionedPerson(userId);
  const label = person ? getUserDisplayName(person, fallback) : fallback;

  return (
    <UserHoverLink
      user={person}
      disableLink={disableLink}
      className={cn(
        MENTION_BADGE,
        !disableLink && "hover:bg-primary/20 hover:no-underline",
        className
      )}
    >
      @{label}
    </UserHoverLink>
  );
};
