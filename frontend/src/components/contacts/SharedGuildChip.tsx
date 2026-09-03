import { useTranslation } from "react-i18next";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
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

/** One line of the hover card: the community's icon beside its name. */
const GuildLine = ({ guild }: { guild: ChipGuild }) => (
  <span className="flex items-center gap-2">
    <Avatar className="size-4 rounded-[0.3rem]">
      {guild.icon_url ? <AvatarImage src={guild.icon_url} alt="" /> : null}
      <AvatarFallback className="rounded-[0.3rem] bg-primary-foreground/20 text-[0.5rem]">
        {getInitials(guild.name, "G")}
      </AvatarFallback>
    </Avatar>
    <span>{guild.name}</span>
  </span>
);

/**
 * The other communities you have in common with somebody.
 *
 * A row under Ravenloft that points at Sunday Sci-Fi, because the same person
 * is listed there too. Overlapping icons in the order the sections come in, so
 * the chip reads as a pointer further down the page rather than as a set.
 *
 * Icons this small are a signal, not a label, so hovering the stack names the
 * communities in full — one card listing every one of them with its own icon,
 * rather than a tooltip per icon that has to be found and hovered separately.
 *
 * It can only ever name guilds the reader is in — the ids are built from their
 * own guild list — so it resolves entirely against sections already on the
 * page and needs no data of its own.
 *
 * No numeric overflow. A stack of icons this size stays legible well past the
 * number of communities anyone is in, and the card names them all.
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

  // The column stays, because the heading names it and an aligned table reads
  // by its columns; only the icons are dropped where there is no overlap.
  if (shown.length === 0) return null;

  const names = shown.map((guild) => guild.name).join(", ");

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            role="img"
            className={cn("flex shrink-0 items-center", className)}
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
        </TooltipTrigger>
        <TooltipContent side="top" className="flex flex-col gap-1.5 px-3 py-2">
          <span className="text-primary-foreground/70">{t("columns.alsoIn")}</span>
          {shown.map((guild) => (
            <GuildLine key={guild.id} guild={guild} />
          ))}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};
