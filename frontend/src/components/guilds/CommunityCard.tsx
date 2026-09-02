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
import { Loader2, Users } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CommunityGuildRead } from "@/api/generated/initiativeAPI.schemas";
import { AgeConfirmationDialog } from "@/components/guilds/AgeConfirmationDialog";
import { GuildAvatar } from "@/components/guilds/GuildSidebar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useJoinCommunityGuild } from "@/hooks/useCommunities";
import { useGuilds } from "@/hooks/useGuilds";
import { renderableBanner } from "@/lib/banner";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { guildCategoryLabel } from "@/lib/guildCategories";
import { guildPath } from "@/lib/guildUrl";

export const CommunityCard = ({ guild }: { guild: CommunityGuildRead }) => {
  const { t } = useTranslation(["guilds", "common"]);
  const navigate = useNavigate();
  const { refreshGuilds, switchGuild } = useGuilds();
  const join = useJoinCommunityGuild();
  const { user } = useAuth();
  const { communityAgeGateEnabled } = useAppConfig();
  const [askingAge, setAskingAge] = useState(false);

  // Somebody may only take a place in a listed guild once they have said they
  // are 13 or older. Asked here, before the join, so ticking the box is what
  // joins — the server refuses it either way, and being refused after clicking
  // Join is a worse way to be asked a question you can answer.
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

  const banner = renderableBanner(guild.banner);

  return (
    <>
      <AgeConfirmationDialog
        open={askingAge}
        onOpenChange={setAskingAge}
        onConfirmed={() => void performJoin()}
      />
      <Card className="flex h-full flex-col overflow-hidden">
        {banner.image_url ? (
          <img
            src={banner.image_url}
            alt=""
            className="aspect-[4/1] w-full object-cover"
            loading="lazy"
          />
        ) : (
          <div
            className="aspect-[4/1] w-full"
            style={{ backgroundColor: banner.color }}
            aria-hidden="true"
          />
        )}
        <CardContent className="flex flex-1 flex-col gap-3 p-4">
          <div className="flex items-start gap-3">
            <GuildAvatar name={guild.name} icon={guild.icon_url} active={false} />
            <div className="min-w-0 flex-1">
              <h3 className="truncate font-semibold text-base" title={guild.name}>
                {guild.name}
              </h3>
              <p className="flex flex-wrap items-center gap-x-1.5 text-muted-foreground text-xs">
                {/* Who is here now, then how many there are in all. A guild with
                  nobody in it says nothing rather than "0 online", which reads
                  as a verdict on the guild rather than on the moment. */}
                {guild.online_count > 0 ? (
                  <>
                    <span className="flex items-center gap-1 font-medium text-emerald-600 dark:text-emerald-400">
                      <span className="size-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
                      {t("guilds:community.onlineCount", { count: guild.online_count })}
                    </span>
                    <span aria-hidden="true">·</span>
                  </>
                ) : null}
                <span className="flex items-center gap-1">
                  <Users className="h-3 w-3" aria-hidden="true" />
                  {t("guilds:memberCount", { count: guild.member_count })}
                </span>
              </p>
            </div>
          </div>

          <p
            className={
              guild.description
                ? "line-clamp-3 text-muted-foreground text-sm"
                : "text-muted-foreground/70 text-sm italic"
            }
          >
            {guild.description || t("guilds:community.noDescription")}
          </p>

          {guild.categories.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {guild.categories.map((category) => (
                <Badge key={category} variant="secondary" className="font-normal">
                  {guildCategoryLabel(category, t)}
                </Badge>
              ))}
            </div>
          ) : null}

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
        </CardContent>
      </Card>
    </>
  );
};
