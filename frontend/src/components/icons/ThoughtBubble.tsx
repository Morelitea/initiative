/**
 * A thought bubble, drawn to lucide's grid.
 *
 * Lucide has no thought bubble, and the nearest thing it has is the wrong
 * thing: `message-circle` is a speech bubble, and a status is what somebody is
 * thinking about rather than something they said to you. So this is drawn here
 * to lucide's own spec — a 24×24 box, a 2px stroke with round caps and joins —
 * and built with `createLucideIcon`, so it takes the same props and sizes the
 * same way as every other icon in the app.
 *
 * The cloud is the union of four circles, so the outline has no corners in it
 * at any size, and it fills the box out to lucide's margin. One trailing dot
 * rather than the pair the bubble wears on screen: at the size an icon is
 * actually read, a second dot is a smudge, and the room it costs is room the
 * cloud is better off having.
 */

import { createLucideIcon } from "lucide-react";

export const ThoughtBubble = createLucideIcon("thought-bubble", [
  [
    "path",
    {
      d: "M6.78 14.81A5.22 5.22 0 1 1 8.34 4.51A5.33 5.33 0 0 1 17.92 6.84A4.78 4.78 0 1 1 15.51 16.03A5.43 5.43 0 0 1 6.81 14.83Z",
      key: "cloud",
    },
  ],
  ["circle", { cx: "5.37", cy: "19.93", r: "1.74", key: "tail" }],
]);
