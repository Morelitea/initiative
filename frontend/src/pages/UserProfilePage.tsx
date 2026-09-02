import { useParams } from "@tanstack/react-router";
import { Loader2, UserX } from "lucide-react";
import { useTranslation } from "react-i18next";

import { TOOL_TRAY_SURFACE } from "@/components/guildHome/GuildToolRail";
import { CommunityCard } from "@/components/guilds/CommunityCard";
import { PageBanner } from "@/components/PageBanner";
import { StatusMessage } from "@/components/StatusMessage";
import { UserHandle } from "@/components/UserHandle";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { ProfileJoined } from "@/components/user/ProfileJoined";
import { ProfileStatus } from "@/components/user/ProfileStatus";
import { ProfileTrophies } from "@/components/user/ProfileTrophies";
import { useAuth } from "@/hooks/useAuth";
import { useUserCommunities, useUserProfile } from "@/hooks/useUsers";
import { profileBanner } from "@/lib/profileBanner";
import { resolveTrophies } from "@/lib/profileDecorations";
import { cn } from "@/lib/utils";

/**
 * A person's profile.
 *
 * Built like a community's front page, because it is the same kind of page: a
 * banner running the full width of the content area with the name on it, the
 * picture and the line they wrote under it, and then the same tray a community
 * has — a rail of circles standing out of it, and everything the page has to
 * show sitting in the surface beneath them. What a community's admin sets
 * there, a decoration sets here; where a community's rail switches its tray
 * between tables of projects and documents, a profile's rail is the trophies
 * and the tray holds the communities the person is in.
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
  const { data: communities } = useUserCommunities(handle);

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
  // The tray is drawn by whichever of its two halves is there: the rail closes
  // into a bar of its own when there are no communities under it, and the
  // communities round off their own top when there are no trophies over them.
  const shelved = communities ?? [];
  const hasTrophies = resolveTrophies(profile.profile_decorations).length > 0;

  return (
    <div className="space-y-6">
      {banner ? <PageBanner banner={banner} title={name} /> : null}

      {/* Everything under the banner has to paint over the tail of its fade,
          which a plain block would not. */}
      <div className="relative z-10 space-y-6">
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
            <ProfileJoined joinedAt={profile.joined_at} className="ms-auto pb-1" />
          </div>
        </div>

        {/* The rail and what it stands out of are one tray, the way the
            community front page has it: the circles are the surface's top edge
            rising, and what the page has to show sits in the same surface
            underneath them. */}
        <div>
          <ProfileTrophies
            decorations={profile.profile_decorations}
            continues={shelved.length > 0}
          />
          {shelved.length > 0 ? (
            <div
              className={cn(
                "px-3 pt-1 pb-3 sm:px-4 sm:pb-4",
                hasTrophies ? "rounded-b-2xl" : "rounded-2xl",
                TOOL_TRAY_SURFACE
              )}
            >
              <section className="space-y-3">
                <h2 className="px-1 font-medium text-muted-foreground text-sm">
                  {t("profiles:guilds.title")}
                </h2>
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {shelved.map((guild) => (
                    <CommunityCard key={guild.id} guild={guild} />
                  ))}
                </div>
              </section>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
};
