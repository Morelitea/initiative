/**
 * The face of a guild card: its banner, avatar, name, who is there, what it
 * says about itself and its shelves. The community directory and the guild
 * rail's expanded view both show a guild this way; what a card offers below
 * that (join, open, nothing at all) is the caller's.
 *
 * The avatar is passed in rather than drawn here, because the rail's carries
 * marks the directory's never does (unread, closed, a temporary grant).
 */

import { Users } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { GuildRead } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { renderableBanner } from "@/lib/banner";
import { guildCategoryLabel } from "@/lib/guildCategories";
import { cn } from "@/lib/utils";

export const GuildCardFace = ({
  guild,
  avatar,
  aside,
  meta,
  className,
  children,
}: {
  guild: Pick<
    GuildRead,
    "name" | "description" | "categories" | "member_count" | "online_count" | "banner"
  >;
  avatar: ReactNode;
  /** Sits at the end of the name line. */
  aside?: ReactNode;
  /** A further line under who is there. */
  meta?: ReactNode;
  className?: string;
  children?: ReactNode;
}) => {
  const { t } = useTranslation(["guilds", "common"]);
  // Every card has a banner: the guild's artwork, or the colour it wears
  // instead, which costs no fetch at all.
  const banner = renderableBanner(guild.banner);

  return (
    <Card className={cn("flex h-full flex-col overflow-hidden", className)}>
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
          {avatar}
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <h3 className="min-w-0 truncate font-semibold text-base" title={guild.name}>
                {guild.name}
              </h3>
              {aside}
            </div>
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
            {meta}
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

        {children}
      </CardContent>
    </Card>
  );
};
