import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useUserCommunities } from "@/hooks/useUsers";
import { getInitials } from "@/lib/initials";
import { resolveUploadUrl } from "@/lib/uploadUrl";

/**
 * The communities on a profile.
 *
 * Only the ones that opted into the directory, which the server decides — a
 * community someone is in that never listed itself is nobody else's business,
 * and never reaches here to be filtered out. Nothing shows where there are
 * none, rather than an empty heading.
 *
 * Where each one goes depends on the reader: a member goes in, and anyone else
 * goes to its card in the directory, where there is something they can do. The
 * community's own pages need membership, so sending a stranger to one would be
 * a link that only ever answers "no".
 */
export const ProfileCommunities = ({ handle }: { handle: string }) => {
  const { t } = useTranslation("profiles");
  const { data: communities } = useUserCommunities(handle);

  if (!communities?.length) return null;

  return (
    <section className="space-y-3">
      <h2 className="font-medium text-muted-foreground text-sm">{t("guilds.title")}</h2>
      <ul className="flex flex-wrap gap-2">
        {communities.map((guild) => {
          const chip = (
            <>
              <Avatar className="size-7">
                {guild.icon_url ? (
                  <AvatarImage src={resolveUploadUrl(guild.icon_url) ?? undefined} alt="" />
                ) : null}
                <AvatarFallback className="text-xs">{getInitials(guild.name)}</AvatarFallback>
              </Avatar>
              <span className="font-medium text-sm">{guild.name}</span>
            </>
          );
          const className =
            "flex items-center gap-2 rounded-full border py-1 pr-3 pl-1 transition-colors hover:bg-accent";
          return (
            <li key={guild.id}>
              {guild.already_member ? (
                <Link to="/c/$guildId" params={{ guildId: String(guild.id) }} className={className}>
                  {chip}
                </Link>
              ) : (
                <Link to="/communities" search={{ q: guild.name }} className={className}>
                  {chip}
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
};
