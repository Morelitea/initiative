import type { CSSProperties } from "react";

import { cellsFromLayout, pathFromLayout, type PixelLayout } from "./pixelLayout";

// 12x12 beveled pixel square — looks like a chunky dropped block.
const SQUARE_LAYOUT: PixelLayout = [
  "            ",
  "  11111111  ",
  "  11111111  ",
  "  11111111  ",
  "  11111111  ",
  "  11111111  ",
  "  11111111  ",
  "  11111111  ",
  "  11111111  ",
  "            ",
  "            ",
  "            ",
];

export const PIXEL_SQUARE_PATH = pathFromLayout(SQUARE_LAYOUT);

interface PixelSquareProps {
  size?: number;
  color?: string;
  className?: string;
  style?: CSSProperties;
}

export const PixelSquare = ({
  size = 24,
  color = "#F472B6",
  className,
  style,
}: PixelSquareProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 12 12"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ imageRendering: "pixelated", shapeRendering: "crispEdges", ...style }}
    aria-hidden="true"
  >
    {cellsFromLayout(SQUARE_LAYOUT).map(({ x, y }) => (
      <rect key={`${x},${y}`} x={x} y={y} width="1" height="1" fill={color} />
    ))}
  </svg>
);
