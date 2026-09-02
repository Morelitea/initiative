import { useTranslation } from "react-i18next";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { getInitials } from "@/lib/initials";
import { cn } from "@/lib/utils";

export interface ChipGuild {
  id: number;
  name: string;
  icon_url?: string | null;
}

interface SharedGuildChipProps {
  /** Every guild the reader shares with this person, in rail order. */
  sharedGuildIds: number[];
  /** The section this row sits in, dropped from the chip. Omit in Favorites. */
  omitGuildId?: number;
  /** The page's sections, which already carry each guild's name and icon. */
  guilds: Map<number, ChipGuild>;
  className?: string;
}

/**
 * The other communities you have in common with somebody.
 *
 * A row under Ravenloft that points at Sunday Sci-Fi, because the same person
 * is listed there too. Overlapping icons in the order the sections come in, so
 * the chip reads as a pointer further down the page rather than as a set.
 *
 * It can only ever name guilds the reader is in — the ids are built from their
 * own guild list — so it resolves entirely against sections already on the
 * page and needs no data of its own.
 *
 * No numeric overflow. A stack of icons this size stays legible well past the
 * number of communities anyone is in, and the title names them all.
 */
export const SharedGuildChip = ({
  sharedGuildIds,
  omitGuildId,
  guilds,
  className,
}: SharedGuildChipProps) => {
  const { t } = useTranslation("contacts");

  const shown = sharedGuildIds
    .filter((id) => id !== omitGuildId)
    .map((id) => guilds.get(id))
    .filter((guild): guild is ChipGuild => guild !== undefined);

  // No chip and no reserved space: most rows in most communities have none,
  // and a column of blank gaps reads as missing data.
  if (shown.length === 0) return null;

  const names = shown.map((guild) => guild.name).join(", ");

  return (
    <span
      role="img"
      className={cn("flex shrink-0 items-center", className)}
      title={t("alsoIn", { guilds: names })}
      aria-label={t("alsoIn", { guilds: names })}
    >
      {shown.map((guild) => (
        <Avatar
          key={guild.id}
          className="-ml-1.5 size-4 rounded-[0.3rem] border border-background first:ml-0"
        >
          {guild.icon_url ? <AvatarImage src={guild.icon_url} alt="" /> : null}
          <AvatarFallback className="rounded-[0.3rem] bg-muted text-[0.5rem] text-muted-foreground">
            {getInitials(guild.name, "G")}
          </AvatarFallback>
        </Avatar>
      ))}
    </span>
  );
};
