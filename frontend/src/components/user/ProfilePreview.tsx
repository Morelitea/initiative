import type {
  CustomStatusOutput,
  ProfileDecorationsOutput,
} from "@/api/generated/initiativeAPI.schemas";
import { UserHandle } from "@/components/UserHandle";
import { Card, CardContent } from "@/components/ui/card";
import { ProfileBadges } from "@/components/user/ProfileBadges";
import { ProfileMeta } from "@/components/user/ProfileMeta";
import { ProfilePicture } from "@/components/user/ProfilePicture";
import { ProfileStatus } from "@/components/user/ProfileStatus";
import { resolveDecoration } from "@/lib/profileDecorations";
import type { AvatarSourceUser, DisplayableUser } from "@/lib/userDisplay";

interface ProfilePreviewProps {
  user: DisplayableUser & AvatarSourceUser;
  decorations: ProfileDecorationsOutput;
  status: CustomStatusOutput;
  /** ISO date the account was created. */
  joinedAt: string;
  /** Re-read the account after the status or the picture is changed here. */
  onChanged?: () => Promise<void> | void;
}

/**
 * Your profile as everyone else sees it, at the size a settings tab has.
 *
 * The page itself runs its banner the full width of the content area, the way
 * a community's front page does. That is a page's shape, not a panel's, so
 * this keeps the banner inside a card and shares the parts instead — the same
 * avatar, badges, status and footer the page draws, so what you see here
 * cannot say something the page does not.
 *
 * The card is also the controls: the picture and the status are both set by
 * clicking them here, because the thing you are looking at is the thing you
 * want to change and a section further down would be a second place to keep
 * in agreement with this one.
 */
export const ProfilePreview = ({
  user,
  decorations,
  status,
  joinedAt,
  onChanged,
}: ProfilePreviewProps) => {
  const banner = resolveDecoration(decorations.banner, "banner");

  return (
    <Card className="overflow-hidden pt-0">
      {/* Painted rather than placed: a background keeps artwork with nothing
          to read in it out of the reading order, and lets it crop at any width. */}
      <div
        className="h-28 w-full bg-center bg-cover bg-muted sm:h-36"
        style={banner ? { backgroundImage: `url(${banner.src})` } : undefined}
      />
      <CardContent className="space-y-4">
        {/* The status above the picture, the same way the page has it: the
            bubble is a thought and the face under it is who is thinking. */}
        <div className="-mt-20 space-y-1">
          <ProfileStatus status={status} editable onSaved={onChanged} />
          <div className="flex flex-wrap items-end gap-4">
            <ProfilePicture
              user={user}
              decorations={decorations}
              online
              editable
              onChanged={onChanged}
              className="size-24 sm:size-28"
            />
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 pb-1">
              <UserHandle user={user} className="font-semibold text-2xl" />
              <ProfileBadges decorations={decorations} />
            </div>
          </div>
        </div>

        <ProfileMeta online joinedAt={joinedAt} />
      </CardContent>
    </Card>
  );
};
