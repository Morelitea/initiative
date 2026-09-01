import type { DisplayableUser } from "@/lib/userDisplay";
import { formatDiscriminator, getUserHandle } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

interface UserHandleProps {
  user: DisplayableUser | null | undefined;
  className?: string;
  /** Muting for the number. Override where the surrounding text is already muted. */
  numberClassName?: string;
}

/**
 * A person's handle: the name they picked, and the number that makes it
 * unique, in a lighter weight beside it.
 *
 * The one place the two are put together on screen. They arrive as separate
 * fields precisely so the number can be styled down — joining them upstream
 * would give away the only thing that makes a wall of digits readable. For
 * plain text (a title, an export) use `getUserHandle` instead.
 */
export const UserHandle = ({ user, className, numberClassName }: UserHandleProps) => {
  if (!user?.username) return null;
  return (
    <span className={cn("inline-flex items-baseline", className)} title={getUserHandle(user)}>
      <span>{user.username}</span>
      <span className={cn("text-muted-foreground/70", numberClassName)}>
        #{formatDiscriminator(user.discriminator)}
      </span>
    </span>
  );
};
