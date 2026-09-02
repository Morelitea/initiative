import { useId } from "react";
import { useTranslation } from "react-i18next";

import type { ProfileDecorationsOutput } from "@/api/generated/initiativeAPI.schemas";
import { TOOL_TRAY_SURFACE } from "@/components/guildHome/GuildToolRail";
import { resolveTrophies } from "@/lib/profileDecorations";
import { cn } from "@/lib/utils";

/**
 * The trophies a profile is wearing, in the order they were put on.
 *
 * The same rail a community puts its tools in: a row of circles standing out
 * of a tray, each with its name printed on the tray under it, and a goo filter
 * welding the two into one silhouette — blur the shapes, push the alpha back
 * to a hard edge, then draw the untouched artwork over the result so the
 * trophies themselves stay sharp (https://css-tricks.com/gooey-effect/). See
 * `GuildToolRail`, whose circles these are the size of and whose tray this is
 * the same surface as.
 *
 * The tray is not decoration. It is what the trophies and their names read
 * against at any brightness, and what makes a collection look like a
 * collection rather than a list. It also holds what the profile has to show —
 * the communities the person is in — the way the guild's tray holds the table
 * of whatever its rail has selected. `continues` says the page carries that
 * surface on below the circles, so the tray opens at the bottom instead of
 * closing into a bar of its own.
 *
 * Only the ones this build can draw: an id from a decoration this deployment
 * doesn't have simply isn't in the row, which is what keeps a profile readable
 * after the store stops offering something.
 */
export const ProfileTrophies = ({
  decorations,
  continues = false,
  className,
}: {
  decorations?: ProfileDecorationsOutput | null;
  /** Whether the page continues the tray below the rail. */
  continues?: boolean;
  className?: string;
}) => {
  const { t } = useTranslation("profiles");
  // Two of these can share a page — the profile card and its preview — so the
  // filter is addressed by an id of its own rather than a constant.
  const filterId = `profile-trophies-goo-${useId().replace(/:/g, "")}`;
  const trophies = resolveTrophies(decorations);
  if (trophies.length === 0) return null;

  return (
    <div className={cn("relative", className)}>
      <svg aria-hidden="true" focusable="false" className="pointer-events-none absolute h-0 w-0">
        <defs>
          <filter
            id={filterId}
            colorInterpolationFilters="sRGB"
            // The blur needs more room than a filter region gets by default,
            // or the tops of the circles are cut off by it.
            x="-5%"
            y="-25%"
            width="110%"
            height="150%"
          >
            <feGaussianBlur in="SourceGraphic" stdDeviation="8" result="blur" />
            <feColorMatrix
              in="blur"
              type="matrix"
              values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 20 -8"
              result="goo"
            />
            <feBlend in="SourceGraphic" in2="goo" />
          </filter>
        </defs>
      </svg>
      <div className="relative" style={{ filter: `url(#${filterId})` }}>
        {/* The tray. Its top edge crosses the trophies at their waist, so half
            of each one stands above it and half is already in it. It closes at
            the bottom only when nothing follows it. */}
        <div
          aria-hidden="true"
          className={cn(
            "absolute inset-x-0 top-13 bottom-0",
            continues ? "rounded-t-2xl" : "rounded-2xl",
            TOOL_TRAY_SURFACE
          )}
        />
        <ul
          aria-label={t("trophyRail")}
          className="relative flex w-max min-w-full items-start overflow-x-auto px-2 pb-2"
        >
          {trophies.map((trophy) => {
            const label = t(trophy.labelKey);
            return (
              <li key={trophy.id} className="flex w-20 flex-col items-center pt-5 text-center">
                <img src={trophy.src} alt="" className="block size-16" />
                <span className="z-5 -mt-3 w-full text-wrap px-1 font-medium text-muted-foreground text-xs">
                  {label}
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
};
