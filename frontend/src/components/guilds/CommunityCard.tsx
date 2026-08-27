/**
 * One guild in the community directory.
 *
 * Everything on this card is what the guild published by opting in — its name,
 * description, icon, shelves, and how many people are already there. A guild
 * the caller is already in keeps its card (so a search still finds it) but
 * offers a way in rather than a way to join twice.
 */

import { useNavigate } from "@tanstack/react-router";
import { Loader2, Users } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { CommunityGuildRead } from "@/api/generated/initiativeAPI.schemas";
import { GuildAvatar } from "@/components/guilds/GuildSidebar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useJoinCommunityGuild } from "@/hooks/useCommunities";
import { useGuilds } from "@/hooks/useGuilds";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { guildCategoryLabel } from "@/lib/guildCategories";
import { guildPath } from "@/lib/guildUrl";

export const CommunityCard = ({ guild }: { guild: CommunityGuildRead }) => {
  const { t } = useTranslation(["guilds", "common"]);
  const navigate = useNavigate();
  const { refreshGuilds, switchGuild } = useGuilds();
  const join = useJoinCommunityGuild();

  const open = () => {
    void switchGuild(guild.id);
    void navigate({ to: guildPath(guild.id, "/") });
  };

  const handleJoin = async () => {
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

  return (
    <Card className="flex h-full flex-col">
      <CardContent className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex items-start gap-3">
          <GuildAvatar name={guild.name} icon={guild.icon_base64} active={false} />
          <div className="min-w-0 flex-1">
            <h3 className="truncate font-semibold text-base" title={guild.name}>
              {guild.name}
            </h3>
            <p className="flex items-center gap-1 text-muted-foreground text-xs">
              <Users className="h-3 w-3" aria-hidden="true" />
              {t("guilds:memberCount", { count: guild.member_count })}
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
  );
};
