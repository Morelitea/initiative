import { useParams } from "@tanstack/react-router";
import { Loader2, UserX } from "lucide-react";
import { useTranslation } from "react-i18next";

import { PageBanner } from "@/components/PageBanner";
import { StatusMessage } from "@/components/StatusMessage";
import { UserHandle } from "@/components/UserHandle";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { ProfileCommunities } from "@/components/user/ProfileCommunities";
import { ProfileMeta } from "@/components/user/ProfileMeta";
import { ProfileStatus } from "@/components/user/ProfileStatus";
import { ProfileTrophies } from "@/components/user/ProfileTrophies";
import { useAuth } from "@/hooks/useAuth";
import { useUserProfile } from "@/hooks/useUsers";
import { profileBanner } from "@/lib/profileBanner";

/**
 * A person's profile.
 *
 * Built like a community's front page, because it is the same kind of page: a
 * banner running the full width of the content area with the name on it, a
 * rail of trophies under it where a community has its tools, and the page
 * riding over the tail of the fade. What a community's admin sets there, a
 * decoration sets here.
 *
 * Public, and the same page whoever opens it: the handle is the name in this
 * product, so nothing here depends on a community deciding whether it renders
 * real names, and how they appear is a fact about the person rather than about
 * a place they happen to share with the reader.
 *
 * Your own status is editable in place; nothing else on it is. The rest is
 * written on Settings → Profile, so there is one place a person edits
 * themselves rather than two that have to agree.
 */
export const UserProfilePage = () => {
  const { t } = useTranslation(["profiles", "common"]);
  const { handle } = useParams({ strict: false }) as { handle: string };
  const { user } = useAuth();

  const { data: profile, isLoading, refetch } = useUserProfile(handle);

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!profile) {
    return (
      <StatusMessage
        icon={<UserX />}
        title={t("notFound.title")}
        description={t("notFound.description")}
        backTo="/"
        backLabel={t("notFound.back")}
      />
    );
  }

  const banner = profileBanner(profile.profile_decorations);
  const mine = user?.id === profile.id;
  const name = <UserHandle user={profile} numberClassName="opacity-70" />;

  return (
    <div className="space-y-6">
      {banner ? <PageBanner banner={banner} title={name} /> : null}

      {/* Everything under the banner has to paint over the tail of its fade,
          which a plain block would not. */}
      <div className="relative z-10 space-y-6">
        <ProfileTrophies decorations={profile.profile_decorations} />

        {/* The status sits above the picture, because it is a thought bubble
            and the thinker is the face under it. */}
        <div className="space-y-1">
          <ProfileStatus
            status={profile.custom_status}
            editable={mine}
            onSaved={() => void refetch()}
          />
          <div className="flex flex-wrap items-end gap-4">
            <ProfileAvatar
              user={profile}
              decorations={profile.profile_decorations}
              presence={profile.presence}
              ring
              className="size-24 sm:size-28"
            />
            {banner ? null : <h1 className="pb-1 font-semibold text-2xl">{name}</h1>}
          </div>
        </div>

        <ProfileMeta presence={profile.presence} joinedAt={profile.joined_at} />

        <ProfileCommunities handle={handle} />
      </div>
    </div>
  );
};
