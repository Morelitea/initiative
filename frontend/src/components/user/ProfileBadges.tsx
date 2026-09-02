import { useId } from "react";
import { useTranslation } from "react-i18next";

import type { ProfileDecorationsOutput } from "@/api/generated/initiativeAPI.schemas";
import { resolveBadges } from "@/lib/profileDecorations";

/**
 * The badges a profile is wearing, in the order they were put on.
 *
 * Only the ones this build can draw: an id from a decoration this deployment
 * doesn't have simply isn't in the row, which is what keeps a profile readable
 * after the store stops offering something.
 *
 * They overlap a tray, and a goo filter welds the two into one silhouette —
 * blur the shapes, push the alpha back to a hard edge, then draw the untouched
 * artwork over the result so the badges themselves stay sharp. The same
 * technique the guild tool rail uses, at the same circle size it uses: a badge
 * is a thing you collect, and a row of them shown at icon size reads as a row
 * of icons. See `GuildToolRail`, whose circles these are the size of.
 *
 * The tray is not decoration. Every badge is a dark disc and a banner is
 * usually a night sky, so a row laid straight on one is a row you cannot see;
 * the tray is what they read against, at any brightness. It is also what makes
 * a collection look like a collection rather than a list.
 */
export const ProfileBadges = ({
  decorations,
}: {
  decorations?: ProfileDecorationsOutput | null;
}) => {
  const { t } = useTranslation("profiles");
  // Two of these can share a page — the profile card and its preview — so the
  // filter is addressed by an id of its own rather than a constant.
  const filterId = `profile-badges-goo-${useId().replace(/:/g, "")}`;
  const badges = resolveBadges(decorations);
  if (badges.length === 0) return null;

  return (
    <>
      <svg aria-hidden="true" focusable="false" className="pointer-events-none absolute h-0 w-0">
        <defs>
          <filter
            id={filterId}
            colorInterpolationFilters="sRGB"
            x="-10%"
            y="-40%"
            width="120%"
            height="180%"
          >
            <feGaussianBlur in="SourceGraphic" stdDeviation="6" result="blur" />
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
        {/* The tray the badges sit on. Inside the filtered layer, so the goo
            welds it to them instead of drawing a panel behind them. */}
        <div
          aria-hidden="true"
          className="absolute inset-x-2 top-1/2 h-10 -translate-y-1/2 rounded-full bg-card/90"
        />
        <ul className="relative flex flex-wrap items-center px-1 py-0.5">
          {badges.map((badge) => {
            const label = t(badge.labelKey);
            return (
              <li key={badge.id}>
                <img src={badge.src} alt={label} title={label} className="block size-16" />
              </li>
            );
          })}
        </ul>
      </div>
    </>
  );
};
