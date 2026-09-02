import { Link } from "@tanstack/react-router";
import { Users } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { CommunityGuildRead } from "@/api/generated/initiativeAPI.schemas";
import { GuildAvatar } from "@/components/guilds/GuildSidebar";

/**
 * The communities on a profile, as the cards a community's own front page
 * fills its tray with are rows.
 *
 * Only the ones that opted into the directory, which the server decides — a
 * community someone is in that never listed itself is nobody else's business,
 * and never reaches here to be filtered out.
 *
 * Each card is a link and nothing else — the directory's card is the one that
 * offers a way in, and this is a list of where somebody is rather than a shelf
 * to shop from. Where it goes depends on the reader: a member goes in, and
 * anyone else goes to that directory card, where there is something they can
 * do. The community's own pages need membership, so sending a stranger to one
 * would be a link that only ever answers "no".
 */
export const ProfileCommunities = ({ communities }: { communities: CommunityGuildRead[] }) => {
  const { t } = useTranslation(["profiles", "guilds"]);

  return (
    <section className="space-y-2">
      <h2 className="px-1 font-medium text-muted-foreground text-sm">
        {t("profiles:guilds.title")}
      </h2>
      <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {communities.map((guild) => {
          const card = (
            <>
              <GuildAvatar name={guild.name} icon={guild.icon_url} active={false} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold text-sm" title={guild.name}>
                  {guild.name}
                </p>
                {/* Who is here now, then how many there are in all — the same
                    two counts the directory card leads with, said the same
                    way. A community with nobody in it says nothing rather than
                    "0 online", which reads as a verdict on the community
                    rather than on the moment. */}
                <p className="flex flex-wrap items-center gap-x-1.5 text-muted-foreground text-xs">
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
            </>
          );
          const className =
            "flex h-full items-center gap-3 rounded-xl border bg-card p-2.5 transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring";
          return (
            <li key={guild.id}>
              {guild.already_member ? (
                <Link to="/c/$guildId" params={{ guildId: String(guild.id) }} className={className}>
                  {card}
                </Link>
              ) : (
                <Link to="/communities" search={{ q: guild.name }} className={className}>
                  {card}
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
};
