/**
 * How many people are in this guild, and how many are here right now.
 *
 * The two counts a guild's front page can answer that no page inside it can:
 * the roster is the size of the place, and the room is whether anything is
 * happening in it. They ride on the banner because that is the one element on
 * the page that is about the guild rather than about its contents.
 *
 * They are dressed in the banner's own ink rather than in the app's palette —
 * a tint of it for the chip, the colour itself for the words — so one stored
 * colour clothes the whole banner and a chip is never the one thing on it that
 * turns out to be unreadable. The presence dot is the exception: green is what
 * "someone is here" means, on any banner.
 */

import { Users } from "lucide-react";
import { useTranslation } from "react-i18next";

import { readableTextShadow, withAlpha } from "@/lib/contrastColor";

export type GuildBannerBadgesProps = {
  memberCount: number;
  onlineCount: number;
  /** The banner's text colour, which these are tinted from. */
  ink: string;
};

export const GuildBannerBadges = ({ memberCount, onlineCount, ink }: GuildBannerBadgesProps) => {
  const { t } = useTranslation("guilds");

  const chip = {
    backgroundColor: withAlpha(ink, 0.16),
    borderColor: withAlpha(ink, 0.35),
    color: ink,
    textShadow: readableTextShadow(ink),
  };

  return (
    <>
      <span
        className="flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium text-xs backdrop-blur-sm"
        style={chip}
      >
        <Users className="h-3.5 w-3.5" aria-hidden="true" />
        {t("memberCount", { count: memberCount })}
      </span>
      {/* A guild with nobody in it says nothing rather than "0 online", which
          reads as a verdict on the guild rather than on the moment. */}
      {onlineCount > 0 ? (
        <span
          className="flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium text-xs backdrop-blur-sm"
          style={chip}
        >
          <span className="size-2 rounded-full bg-emerald-400" aria-hidden="true" />
          {t("community.onlineCount", { count: onlineCount })}
        </span>
      ) : null}
    </>
  );
};
