/**
 * The guild home's tool switcher: one circle per tool, its name underneath.
 *
 * Each circle is a real link carrying `?tool=<route segment>`, so a tool view
 * is shareable, survives a reload, and answers the back button.
 *
 * The circles are the top edge of the tray the table below sits in, not marks
 * laid on the banner: each one's lower half is inside the tray, and an SVG goo
 * filter — blur the shapes, then push the alpha back to a hard edge — welds
 * the two into a single silhouette with a fillet at every neck
 * (https://css-tricks.com/gooey-effect/). Two things follow from that, and
 * both are the point: a tool's name is printed on the tray rather than on
 * whatever the banner happens to be at that height, which is the only way it
 * reads over a photograph at any brightness; and the filter's last step draws
 * the untouched graphic back over the blob, so the words and the icons stay as
 * sharp as they were.
 *
 * Which tool is open is said by size rather than by colour — that circle
 * swells out of the row and drags its neighbours' necks with it, and its name
 * goes to the page's full ink. Size is state, so it holds whatever the reader
 * has asked for about motion; only the travel between sizes, and the swell
 * under the pointer, are motion, and only those are behind `motion-safe`.
 *
 * The rail follows the banner above it: a guild that centres its banner copy
 * gets a centred rail under it, and one that aligns left keeps the circles
 * against the same edge its name sits on. Either way the rail scrolls rather
 * than wrapping once there are more circles than room.
 */

import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { useGuildPath } from "@/lib/guildUrl";
import { TOOL_ICONS, toolNavLabelKey, toolRouteSegment } from "@/lib/tools";
import { cn } from "@/lib/utils";

/**
 * What the tray is made of. The rail renders its top and the page renders the
 * rest of it around the table, so the two say it in one place — and the
 * circles have to be this exact fill for the goo to read as one surface rather
 * than as circles on a panel.
 */
export const TOOL_TRAY_SURFACE = "bg-muted";

/** Where the tray's edge crosses the circles: their waist, so half of each one
 *  stands above the tray and half is already in it. */
const TRAY_EDGE = "top-13";

const GOO_FILTER_ID = "guild-tool-rail-goo";

interface GuildToolRailProps {
  tools: Tool[];
  selected: Tool;
  /** Where the banner above puts its copy. The rail lines up with it. */
  align?: "center" | "left";
}

export const GuildToolRail = ({ tools, selected, align = "left" }: GuildToolRailProps) => {
  // `nav` leads so the derived tool label keys resolve without a namespace
  // prefix — the same call shape the sidebar uses.
  const { t } = useTranslation(["nav", "guildHome"]);
  const gp = useGuildPath();

  return (
    <div className="relative">
      {/* The goo itself: blur everything in the filtered layer, throw the
          faint half of that blur away and the rest back up to full opacity —
          which turns two shapes that merely touch into one shape that flows —
          then blend the original graphic over the result so nothing that has
          to be read went through the blur. */}
      <svg aria-hidden="true" focusable="false" className="pointer-events-none absolute h-0 w-0">
        <defs>
          <filter
            id={GOO_FILTER_ID}
            colorInterpolationFilters="sRGB"
            // The blur needs more room than a filter region gets by
            // default, or the tops of the circles are cut off by it.
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
      <div className="relative" style={{ filter: `url(#${GOO_FILTER_ID})` }}>
        {/* The tray's top edge. It runs the width of the page's content and
            ends flush with this element's bottom, where the page continues it
            around the table. */}
        <div
          aria-hidden="true"
          className={cn("absolute inset-x-0 bottom-0 rounded-t-2xl", TRAY_EDGE, TOOL_TRAY_SURFACE)}
        />
        <nav
          aria-label={t("guildHome:toolRail")}
          className="relative overflow-x-auto px-2 pb-2 sm:px-3"
        >
          {/* `w-max min-w-full` rather than `min-w-max`: the list is at least as
              wide as the rail, so centring has room to act, and grows past it
              when there are more circles than fit, so it still scrolls. */}
          <ul
            className={cn(
              // No gap at all: the circles are close enough that the goo
              // bridges one to the next, so the tray's edge reads as a
              // scalloped surface rather than a row of buttons.
              "flex w-max min-w-full items-start",
              align === "center" && "justify-center"
            )}
          >
            {tools.map((tool) => {
              const Icon = TOOL_ICONS[tool];
              const isSelected = tool === selected;
              return (
                <li key={tool}>
                  <Link
                    to={gp("/")}
                    search={{ tool: toolRouteSegment(tool) }}
                    aria-current={isSelected ? "page" : undefined}
                    className={cn(
                      "group flex w-20 flex-col items-center rounded-lg pt-5 pb-1 text-center outline-none transition-colors",
                      "focus-visible:ring-2 focus-visible:ring-ring"
                    )}
                  >
                    <span
                      className={cn(
                        "flex h-16 w-16 items-center justify-center rounded-full transition-colors",
                        // Every circle is the tray's own fill, so the goo reads
                        // them as the edge of it rising rather than as buttons
                        // laid on it. Which one is selected is said by size
                        // rather than by colour: it stands a good deal taller
                        // than the rest of the row and drags the necks either
                        // side of it up with it.
                        TOOL_TRAY_SURFACE,
                        // The size is state, so it holds however the reader
                        // feels about motion; only the travel between sizes,
                        // and the lift under a pointer, are motion, so only
                        // those are asked for.
                        "motion-safe:transition-transform motion-safe:duration-300 motion-safe:ease-out",
                        isSelected
                          ? "-translate-y-1 scale-125 text-primary"
                          : cn(
                              "text-muted-foreground group-hover:text-foreground",
                              "motion-safe:group-hover:-translate-y-0.5 motion-safe:group-hover:scale-110"
                            )
                      )}
                    >
                      <Icon className="h-6 w-6" />
                    </span>
                    <span
                      className={cn(
                        "w-full px-1 text-xs text-wrap -mt-3 z-5",
                        isSelected
                          ? "font-semibold text-primary"
                          : "font-medium text-muted-foreground group-hover:text-foreground"
                      )}
                    >
                      {t(toolNavLabelKey(tool))}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </div>
  );
};
