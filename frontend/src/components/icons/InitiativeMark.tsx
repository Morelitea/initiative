/**
 * The figure from Initiative's logo, drawn to lucide's grid: the icon for an
 * initiative.
 *
 * The logo is a die whose pip is a person's head: a lowercase "i" with its
 * arms held out. This is that figure without the die around it, drawn to
 * lucide's own spec — a 24×24 box, a 2px stroke with round caps and joins —
 * and built with `createLucideIcon`, so it takes the same props and sizes the
 * same way as every other icon in the app.
 *
 * The stem is an outline rather than a single stroke, so it keeps the logo's
 * broad, round-topped "i" (wider than the head, open at the foot where the
 * logo's stem meets the die's edge), and the arms rise outward at the die's
 * isometric 2:1 slope, clear of the body as they are in the logo.
 *
 * The arms are heavier than a stroke: each is a narrow capsule outlined with
 * the same 2px stroke, so it renders as one solid bar with round ends, as
 * thick as the logo's arms are next to its stem, and still thickens and thins
 * with `strokeWidth` like the rest of the icon.
 */

import { createLucideIcon } from "lucide-react";

export const InitiativeMark = createLucideIcon("initiative-mark", [
  ["circle", { cx: "12", cy: "5", r: "2.5", key: "head" }],
  ["path", { d: "M8.5 21v-6.5a3.5 3.5 0 0 1 7 0v6.5", key: "stem" }],
  [
    "path",
    {
      d: "M6.6 8.96 3.23 7.28a.75.75 0 0 0-.67 1.34l3.37 1.68a.75.75 0 0 0 .67-1.34z",
      key: "arm-left",
    },
  ],
  [
    "path",
    {
      d: "M18.07 10.3 21.44 8.62a.75.75 0 0 0-.67-1.34l-3.37 1.68a.75.75 0 0 0 .67 1.34z",
      key: "arm-right",
    },
  ],
]);
