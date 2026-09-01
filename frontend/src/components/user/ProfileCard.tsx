import { useTranslation } from "react-i18next";

import type {
  CustomStatusOutput,
  ProfileDecorationsOutput,
} from "@/api/generated/initiativeAPI.schemas";
import { UserHandle } from "@/components/UserHandle";
import { Card, CardContent } from "@/components/ui/card";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { ProfileBadges } from "@/components/user/ProfileBadges";
import { formatDate } from "@/lib/formatDate";
import { resolveDecoration } from "@/lib/profileDecorations";
import type { AvatarSourceUser, DisplayableUser } from "@/lib/userDisplay";

interface ProfileCardProps {
  user: DisplayableUser & AvatarSourceUser;
  decorations: ProfileDecorationsOutput;
  status: CustomStatusOutput;
  online: boolean;
  /** ISO date the account was created. */
  joinedAt: string;
  /**
   * `h1` on the profile page, where the handle is the page's subject. Anywhere
   * the card is embedded under a heading of its own, it stays a `p`.
   */
  nameAs?: "h1" | "p";
}

/**
 * A person's profile: the banner, the picture in its frame, the handle, the
 * badges, what they are up to, and whether they are around.
 *
 * One component for both the page and the preview in settings. A preview that
 * showed less than the page would be answering a different question from the
 * one being asked of it — you change what you are wearing to see how you look,
 * so what you see has to be the whole face.
 */
export const ProfileCard = ({
  user,
  decorations,
  status,
  online,
  joinedAt,
  nameAs = "p",
}: ProfileCardProps) => {
  const { t } = useTranslation("profiles");
  const banner = resolveDecoration(decorations.banner, "banner");
  const Name = nameAs;

  return (
    <Card className="overflow-hidden pt-0">
      {/* The banner is artwork with nothing to read in it, so it is painted
          rather than placed: a background keeps it out of the reading order
          and lets it crop at any width. */}
      <div
        className="h-28 w-full bg-center bg-cover bg-muted sm:h-36"
        style={banner ? { backgroundImage: `url(${banner.src})` } : undefined}
      />
      <CardContent className="space-y-4">
        <div className="-mt-14 flex flex-wrap items-end gap-4">
          <ProfileAvatar
            user={user}
            decorations={decorations}
            online={online}
            ring
            className="size-24 sm:size-28"
          />
          {/* Badges sit against the name, which is what a badge is for. Put
              at the end of the row they read as decoration of the card rather
              than of the person. */}
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 pb-1">
            <Name>
              <UserHandle user={user} className="font-semibold text-2xl" />
            </Name>
            <ProfileBadges decorations={decorations} />
          </div>
        </div>

        {status.emoji || status.text ? (
          <p className="flex items-start gap-2 text-base">
            {status.emoji ? (
              <span className="text-xl leading-tight" aria-hidden="true">
                {status.emoji}
              </span>
            ) : null}
            <span className="min-w-0 break-words">{status.text}</span>
          </p>
        ) : (
          <p className="text-muted-foreground text-sm">{t("noStatus")}</p>
        )}

        <dl className="flex flex-wrap gap-x-8 gap-y-2 border-t pt-4 text-sm">
          <div className="flex items-center gap-2">
            {/* The dot and the word say it; the label is here for a reader who
                gets the list read out rather than shown. */}
            <dt className="sr-only">{t("presence.label")}</dt>
            <dd className="flex items-center gap-1.5 font-medium">
              <span
                className={`size-2 rounded-full ${
                  online ? "bg-emerald-500" : "bg-muted-foreground/40"
                }`}
                aria-hidden="true"
              />
              {online ? t("presence.online") : t("presence.offline")}
            </dd>
          </div>
          <div className="flex items-center gap-2">
            <dt className="text-muted-foreground">{t("joined.label")}</dt>
            <dd className="font-medium">{formatDate(joinedAt)}</dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
};
