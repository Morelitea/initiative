import { useParams } from "@tanstack/react-router";
import { Loader2, UserX } from "lucide-react";
import { useTranslation } from "react-i18next";

import { StatusMessage } from "@/components/StatusMessage";
import { ProfileCard } from "@/components/user/ProfileCard";
import { useUserProfile } from "@/hooks/useUsers";

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
  const { handle } = useParams({ strict: false }) as { handle: string };

  const { data: profile, isLoading } = useUserProfile(handle);

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

  return (
    <div className="mx-auto max-w-3xl">
      <ProfileCard
        user={profile}
        decorations={profile.profile_decorations}
        status={profile.custom_status}
        online={profile.online}
        joinedAt={profile.joined_at}
        nameAs="h1"
      />
    </div>
  );
};
