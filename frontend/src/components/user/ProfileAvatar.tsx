import type { ProfileDecorationsOutput } from "@/api/generated/initiativeAPI.schemas";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { resolveDecoration } from "@/lib/profileDecorations";
import {
  type AvatarSourceUser,
  type DisplayableUser,
  getAvatarSrc,
  getInitialsForUser,
  getUserDisplayName,
} from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

interface ProfileAvatarProps {
  user: DisplayableUser & AvatarSourceUser;
  decorations?: ProfileDecorationsOutput | null;
  /** Show the "has the app open" dot. Left off where presence isn't known. */
  online?: boolean;
  /** Sizing for the avatar itself; everything else scales off it. */
  className?: string;
}

/**
 * A person's picture, wearing whatever they have put around it.
 *
 * The frame is drawn *over* the picture rather than replacing it, and slightly
 * outside it, so the ring reads as something worn rather than as a crop. It is
 * decoration and carries no information, so it is hidden from assistive
 * technology; the presence dot is not, and says so in words.
 */
export const ProfileAvatar = ({ user, decorations, online, className }: ProfileAvatarProps) => {
  const frame = resolveDecoration(decorations?.frame, "frame");

  return (
    <div className={cn("relative shrink-0", className)}>
      <Avatar className="h-full w-full">
        <AvatarImage src={getAvatarSrc(user)} alt={getUserDisplayName(user, "")} />
        <AvatarFallback userId={user.id ?? undefined}>{getInitialsForUser(user)}</AvatarFallback>
      </Avatar>
      {frame ? (
        <img
          src={frame.src}
          alt=""
          aria-hidden="true"
          className="pointer-events-none absolute -inset-[7%] max-w-none"
        />
      ) : null}
      {online ? (
        <span className="absolute right-0 bottom-0 block size-1/4 rounded-full bg-emerald-500 ring-2 ring-background" />
      ) : null}
    </div>
  );
};
