import type { ProfileDecorationsOutput } from "@/api/generated/initiativeAPI.schemas";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { FRAME_INSET, FRAME_SIZE, resolveDecoration } from "@/lib/profileDecorations";
import {
  type AvatarSourceUser,
  type DisplayableUser,
  getAvatarSrc,
  getInitialsForUser,
  getUserDisplayName,
} from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

interface ProfileAvatarProps {
  user: (DisplayableUser & AvatarSourceUser) | null | undefined;
  decorations?: ProfileDecorationsOutput | null;
  /** Show the "has the app open" dot. Left off where presence isn't known. */
  online?: boolean;
  /**
   * Separate the picture from artwork behind it with a ring in the card's own
   * colour — for an avatar that overlaps a banner. Ignored when a frame is
   * worn, because then the frame is the edge and a ring under it reads as a gap
   * between the picture and the thing meant to be holding it.
   */
  ring?: boolean;
  /** Sizing for the avatar itself; everything else scales off it. */
  className?: string;
}

/**
 * A person's picture, wearing whatever they have put around it.
 *
 * The frame is artwork with a hole in it and the picture fills the hole. Every
 * frame is drawn to the same aperture, so one inset seats all of them and a
 * frame published later needs no code here. It carries no information, so it is
 * hidden from assistive technology; the presence dot is not, and says so in
 * words wherever it appears.
 */
export const ProfileAvatar = ({
  user,
  decorations,
  online,
  ring,
  className,
}: ProfileAvatarProps) => {
  const frame = resolveDecoration(decorations?.frame, "frame");

  return (
    <div
      className={cn(
        "relative shrink-0 rounded-full",
        ring && !frame && "ring-4 ring-card",
        className
      )}
    >
      <Avatar className="h-full w-full">
        <AvatarImage src={getAvatarSrc(user)} alt={getUserDisplayName(user, "")} />
        <AvatarFallback userId={user?.id ?? undefined}>{getInitialsForUser(user)}</AvatarFallback>
      </Avatar>
      {frame ? (
        <img
          src={frame.src}
          alt=""
          aria-hidden="true"
          className="pointer-events-none absolute max-w-none"
          style={{ width: FRAME_SIZE, height: FRAME_SIZE, left: FRAME_INSET, top: FRAME_INSET }}
        />
      ) : null}
      {online ? (
        <span className="absolute right-0 bottom-0 block size-1/4 rounded-full bg-emerald-500 ring-2 ring-background" />
      ) : null}
    </div>
  );
};
