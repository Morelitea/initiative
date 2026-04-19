import type { CSSProperties } from "react";

import { cellsFromLayout, type PixelLayout } from "./pixelLayout";

// 24x24 d20 silhouette. 1 = base purple, h = highlight, d = dark edge.
// Stylized as a flat hex (icosahedron flat-projected) — the upper triangle
// is the visible "face" we render the rolled number into.
const D20_LAYOUT: PixelLayout = [
  "        ddd        ",
  "      dd1d1dd      ",
  "    dd11hd111dd    ",
  "  dd1hhhhdhhh11dd  ",
  "dd1hhdddddddddhhhdd",
  "ddddd111dhd111ddddd",
  "dd11111dh11d11111dd",
  "d1d1111dh11d1111d1d",
  "d1d111dh1111d111d1d",
  "d11d11dh1111d11d11d",
  "d11d1dh111111d1d11d",
  "d111dh11111111d111d",
  "d111ddddddddddd111d",
  "d1dd1d1111111d1dd1d",
  "dd1111d11111d1111dd",
  "  dd111d111d111dd  ",
  "    dd11d1d11dd    ",
  "      dd1d1dd      ",
  "        ddd        ",
];

const D20_VIEW_W = D20_LAYOUT[0].length;
const D20_VIEW_H = D20_LAYOUT.length;

const D20_BASE = "#A78BFA"; // violet-400
const D20_HIGHLIGHT = "#DDD6FE"; // violet-200
const D20_DARK = "#5B21B6"; // violet-800

const NUMBER_TEXT_FILL = "#1E1B4B"; // indigo-950 — high contrast on violet

interface PixelD20Props {
  /** Face value to display in the center of the die. */
  value: number;
  size?: number;
  className?: string;
  style?: CSSProperties;
}

export const PixelD20 = ({ value, size = 96, className, style }: PixelD20Props) => (
  <svg
    width={size}
    height={size}
    viewBox={`0 0 ${D20_VIEW_W} ${D20_VIEW_H}`}
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ imageRendering: "pixelated", shapeRendering: "crispEdges", ...style }}
    aria-hidden="true"
  >
    {cellsFromLayout(D20_LAYOUT).map(({ x, y, char }) => {
      const fill = char === "d" ? D20_DARK : char === "h" ? D20_HIGHLIGHT : D20_BASE;
      return <rect key={`${x},${y}`} x={x} y={y} width="1" height="1" fill={fill} />;
    })}
    {/* The face number. Uses a pixel-style font-family stack and is offset
        so it sits visually centered on the silhouette. */}
    <text
      x={D20_VIEW_W / 2}
      y={D20_VIEW_H / 2}
      textAnchor="middle"
      dominantBaseline="central"
      fontSize="4"
      fontFamily="'Press Start 2P', 'VT323', ui-monospace, monospace"
      fontWeight="bold"
      fill={NUMBER_TEXT_FILL}
      style={{ fontFamily: "'Press Start 2P', 'VT323', ui-monospace, monospace" }}
    >
      {value}
    </text>
  </svg>
);
