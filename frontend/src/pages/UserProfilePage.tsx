import { useParams } from "@tanstack/react-router";
import { Loader2, UserX } from "lucide-react";
import { useTranslation } from "react-i18next";

import { StatusMessage } from "@/components/StatusMessage";
import { UserHandle } from "@/components/UserHandle";
import { Card, CardContent } from "@/components/ui/card";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { ProfileBadges } from "@/components/user/ProfileBadges";
import { useUserProfile } from "@/hooks/useUsers";
import { formatDate } from "@/lib/formatDate";
import { resolveDecoration } from "@/lib/profileDecorations";

/**
 * A person's profile.
 *
 * Public, and the same page whoever opens it: the handle is the name in this
 * product, so nothing here depends on a community deciding whether it renders
 * real names, and "online" is a fact about the person rather than about a
 * place they happen to share with the reader.
 *
 * Read-only for everyone, including its owner: what is on it is written on
 * Settings → Profile, so there is one place a person edits themselves rather
 * than two that have to agree.
 */
export const UserProfilePage = () => {
  const { t } = useTranslation(["profiles", "common"]);
  const { userId: userIdParam } = useParams({ strict: false }) as { userId: string };
  const userId = Number(userIdParam);

  const { data: profile, isLoading } = useUserProfile(Number.isFinite(userId) ? userId : null);

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

  const banner = resolveDecoration(profile.profile_decorations.banner, "banner");
  const { emoji: statusEmoji, text: statusText } = profile.custom_status;

  return (
    <div className="mx-auto max-w-3xl">
      <Card className="overflow-hidden pt-0">
        {/* The banner is artwork with nothing to read in it, so it is painted
            rather than placed: a background keeps it out of the reading order
            and lets it crop at any width. */}
        <div
          className="h-28 w-full bg-center bg-cover bg-muted sm:h-40"
          style={banner ? { backgroundImage: `url(${banner.src})` } : undefined}
        />
        <CardContent className="space-y-4">
          <div className="-mt-14 flex flex-wrap items-end gap-4 sm:-mt-16">
            <ProfileAvatar
              user={profile}
              decorations={profile.profile_decorations}
              online={profile.online}
              className="size-24 rounded-full ring-4 ring-card sm:size-28"
            />
            <div className="min-w-0 flex-1 pb-1">
              {/* The handle is the name here, so it is the heading rather than
                  a subtitle under one. */}
              <h1>
                <UserHandle user={profile} className="font-semibold text-2xl" />
              </h1>
            </div>
            <ProfileBadges decorations={profile.profile_decorations} />
          </div>

          {statusEmoji || statusText ? (
            <p className="flex items-start gap-2 text-base">
              {statusEmoji ? (
                <span className="text-xl leading-tight" aria-hidden="true">
                  {statusEmoji}
                </span>
              ) : null}
              <span className="min-w-0 break-words">{statusText}</span>
            </p>
          ) : (
            <p className="text-muted-foreground text-sm">{t("noStatus")}</p>
          )}

          <dl className="flex flex-wrap gap-x-8 gap-y-2 border-t pt-4 text-sm">
            <div className="flex items-center gap-2">
              {/* The dot and the word say it; the label is here for a reader
                  who gets the list read out rather than shown. */}
              <dt className="sr-only">{t("presence.label")}</dt>
              <dd className="flex items-center gap-1.5 font-medium">
                <span
                  className={`size-2 rounded-full ${
                    profile.online ? "bg-emerald-500" : "bg-muted-foreground/40"
                  }`}
                  aria-hidden="true"
                />
                {profile.online ? t("presence.online") : t("presence.offline")}
              </dd>
            </div>
            <div className="flex items-center gap-2">
              <dt className="text-muted-foreground">{t("joined.label")}</dt>
              <dd className="font-medium">{formatDate(profile.joined_at)}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>
    </div>
  );
};
