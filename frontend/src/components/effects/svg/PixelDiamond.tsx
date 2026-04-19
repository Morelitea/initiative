import type { CSSProperties } from "react";

import { cellsFromLayout, pathFromLayout, type PixelLayout } from "./pixelLayout";

// 12x12 pixel rhombus / diamond.
const DIAMOND_LAYOUT: PixelLayout = [
  "            ",
  "     11     ",
  "    1111    ",
  "   111111   ",
  "  11111111  ",
  " 1111111111 ",
  "  11111111  ",
  "   111111   ",
  "    1111    ",
  "     11     ",
  "            ",
  "            ",
];

export const PIXEL_DIAMOND_PATH = pathFromLayout(DIAMOND_LAYOUT);

interface PixelDiamondProps {
  size?: number;
  color?: string;
  className?: string;
  style?: CSSProperties;
}

export const PixelDiamond = ({
  size = 24,
  color = "#60A5FA",
  className,
  style,
}: PixelDiamondProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 12 12"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ imageRendering: "pixelated", shapeRendering: "crispEdges", ...style }}
    aria-hidden="true"
  >
    {cellsFromLayout(DIAMOND_LAYOUT).map(({ x, y }) => (
      <rect key={`${x},${y}`} x={x} y={y} width="1" height="1" fill={color} />
    ))}
  </svg>
);
