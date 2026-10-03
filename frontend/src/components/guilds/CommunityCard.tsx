/**
 * One guild in the community directory.
 *
 * Everything on this card is what the guild published by opting in — its
 * banner, name, description, icon, shelves, and how many people are already
 * there. A guild the caller is already in keeps its card (so a search still
 * finds it) but offers a way in rather than a way to join twice.
 *
 * The two pictures arrive as URLs and are fetched per card, not carried in the
 * directory payload: a page is up to sixty of these, and each one is then
 * cached against a URL that changes only when the picture does. Every card has
 * a banner: the guild's artwork, or the colour it wears instead, which costs
 * no fetch at all.
 */

import { useNavigate } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { DirectoryCommunityRead } from "@/api/generated/initiativeAPI.schemas";
import { AgeConfirmationDialog } from "@/components/guilds/AgeConfirmationDialog";
import { GuildCardFace } from "@/components/guilds/GuildCardFace";
import { GuildAvatar } from "@/components/guilds/GuildSidebar";
import { ReportButton } from "@/components/moderation/ReportButton";
import { Button } from "@/components/ui/button";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useJoinCommunityGuild } from "@/hooks/useCommunities";
import { useGuilds } from "@/hooks/useGuilds";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { guildPath } from "@/lib/guildUrl";

export const CommunityCard = ({ guild }: { guild: DirectoryCommunityRead }) => {
  const { t } = useTranslation(["guilds", "common"]);
  const navigate = useNavigate();
  const { refreshGuilds, switchGuild } = useGuilds();
  const join = useJoinCommunityGuild();
  const { user } = useAuth();
  const { communityAgeGateEnabled } = useAppConfig();
  const [askingAge, setAskingAge] = useState(false);

  // Somebody may only take a place in a listed guild once they have said they
  // are old enough. Asked here, before the join, so answering is what joins —
  // the server refuses it either way, and being refused after clicking Join is
  // a worse way to be asked a question you can answer.
  //
  // This is the only place the question is put. An account that never answers
  // it keeps every community it was invited to and the whole of the app around
  // this card; all it cannot do is join a community from the directory.
  const needsAgeConfirmation = communityAgeGateEnabled && !user?.age_confirmed_at;

  const open = () => {
    void switchGuild(guild.id);
    void navigate({ to: guildPath(guild.id, "/") });
  };

  // The join itself, with no age check in it. The dialog resumes through this
  // rather than through ``handleJoin``: it calls back the moment the
  // confirmation is recorded, which is before React has re-rendered this card
  // with the refreshed account — so a check here would still read the stale
  // "not confirmed" and reopen the dialog it was just dismissed from.
  const performJoin = async () => {
    try {
      await join.mutateAsync(guild.id);
      // The switcher is built from the caller's memberships, so it has to learn
      // about the new one before we navigate into it.
      await refreshGuilds();
      toast.success(t("guilds:community.joinedToast", { guild: guild.name }));
      open();
    } catch (error) {
      console.error(error);
      toast.error(getErrorMessage(error, "guilds:community.joinFailed"));
    }
  };

  const handleJoin = () => {
    if (needsAgeConfirmation) {
      setAskingAge(true);
      return;
    }
    void performJoin();
  };

  return (
    <>
      <AgeConfirmationDialog
        open={askingAge}
        onOpenChange={setAskingAge}
        onConfirmed={() => void performJoin()}
      />
      <GuildCardFace
        guild={guild}
        avatar={<GuildAvatar name={guild.name} icon={guild.icon_url} active={false} />}
        aside={
          // A listing is the deployment's to answer for, not the community's
          // own — so no community is sent with it.
          <ReportButton
            targetType="directory_listing"
            targetId={guild.id}
            guildId={null}
            className="-mt-1 shrink-0"
          />
        }
      >
        <div className="mt-auto pt-1">
          {guild.already_member ? (
            <Button variant="outline" className="w-full" onClick={open}>
              {t("guilds:community.open")}
            </Button>
          ) : (
            <Button className="w-full" onClick={handleJoin} disabled={join.isPending}>
              {join.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  {t("guilds:community.joining")}
                </>
              ) : (
                t("guilds:community.join")
              )}
            </Button>
          )}
        </div>
      </GuildCardFace>
    </>
  );
};
