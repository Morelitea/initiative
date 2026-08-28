/**
 * Lucide's `galaxy`, vendored.
 *
 * The icon is in the lucide icon set but has not shipped in a `lucide-react`
 * release yet (1.34.0, the latest, has no `Galaxy` export), so it is built here
 * from the same path data with lucide's own factory: identical props, sizing,
 * and stroke behaviour to every other icon in the app. Delete this file and
 * import `Galaxy` from `lucide-react` once a release carries it.
 *
 * Source: https://github.com/lucide-icons/lucide/blob/main/icons/galaxy.svg (ISC)
 */

import { createLucideIcon } from "lucide-react";

export const Galaxy = createLucideIcon("galaxy", [
  [
    "path",
    {
      d: "M16.005 15.108a5.041 6.52 28.25 00-8.008-6.217 5.041 6.52 28.25 008.008 6.217A11.884 7.288-60.76 014.029 7.001",
      key: "galaxy-arm-a",
    },
  ],
  ["path", { d: "M17 21h.01", key: "galaxy-dot-a" }],
  ["path", { d: "M7 3h.01", key: "galaxy-dot-b" }],
  [
    "path",
    {
      d: "M7.997 8.891a11.885 7.288-60.756 0111.977 8.107",
      key: "galaxy-arm-b",
    },
  ],
  ["circle", { cx: "12", cy: "12", r: "1", fill: "currentColor", key: "galaxy-core" }],
]);
