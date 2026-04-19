import type { CSSProperties } from "react";

import { cellsFromLayout, type PixelLayout } from "./pixelLayout";

// 8x8 four-pointed pixel sparkle.
const SPARKLE_LAYOUT: PixelLayout = [
  "        ",
  "   11   ",
  "   11   ",
  " 111111 ",
  " 111111 ",
  "   11   ",
  "   11   ",
  "        ",
];

interface PixelSparkleProps {
  size?: number;
  color?: string;
  className?: string;
  style?: CSSProperties;
}

export const PixelSparkle = ({
  size = 16,
  color = "#FDE68A", // amber-200
  className,
  style,
}: PixelSparkleProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 8 8"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ imageRendering: "pixelated", shapeRendering: "crispEdges", ...style }}
    aria-hidden="true"
  >
    {cellsFromLayout(SPARKLE_LAYOUT).map(({ x, y }) => (
      <rect key={`${x},${y}`} x={x} y={y} width="1" height="1" fill={color} />
    ))}
  </svg>
);
