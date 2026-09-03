/**
 * The two frames whose colour the wearer picks.
 *
 * Everything else in the catalog is a file, drawn once and served as an image —
 * which is why a pack's artwork looks the same on everybody. These two are
 * drawn here instead, because their colours are not decided until somebody
 * decides them, and an `<img>` cannot be told what to be.
 *
 * Both are cut to the same aperture as every other frame (r=50 in a 128 box),
 * so they seat exactly where a file-backed frame seats and `ProfileAvatar`
 * needs to know nothing about which kind it is holding.
 */

import type { Decoration } from "@/lib/profileDecorations";
import { DEFAULT_TINTS } from "@/lib/profileDecorations";

/** Where the ring runs: the aperture, out to the edge of the box. */
const INNER = 50.6;
const OUTER = 63.4;

interface TintedFrameProps {
  decoration: Decoration;
  /** What the wearer picked. Short or empty falls back to the default. */
  tint?: readonly string[] | null;
  className?: string;
  style?: React.CSSProperties;
}

const colours = (decoration: Decoration, tint?: readonly string[] | null) => {
  const fallback = DEFAULT_TINTS[decoration.id] ?? [];
  return fallback.map((value, index) => tint?.[index] || value);
};

export const TintedFrame = ({ decoration, tint, className, style }: TintedFrameProps) => {
  const [first, second] = colours(decoration, tint);
  // Two of these can share a page, and a gradient is addressed by id.
  const key = `${decoration.id.replace(/\W/g, "")}-${first}-${second ?? ""}`.replace(/#/g, "");

  return (
    <svg
      viewBox="0 0 128 128"
      className={className}
      style={style}
      aria-hidden="true"
      focusable="false"
    >
      <title>{decoration.id}</title>
      <defs>
        {/* One pass of light across the ring, so a flat colour still reads as a
            band with a top and a bottom rather than as a printed circle. */}
        <linearGradient id={`sheen-${key}`} x1="0" y1="0" x2="0.4" y2="1">
          <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.34" />
          <stop offset="52%" stopColor="#FFFFFF" stopOpacity="0" />
          <stop offset="100%" stopColor="#000000" stopOpacity="0.26" />
        </linearGradient>
        <clipPath id={`band-${key}`}>
          <path
            d={`M64 ${64 - OUTER} A${OUTER} ${OUTER} 0 1 0 64 ${64 + OUTER} A${OUTER} ${OUTER} 0 1 0 64 ${64 - OUTER} Z
                M64 ${64 - INNER} A${INNER} ${INNER} 0 1 1 64 ${64 + INNER} A${INNER} ${INNER} 0 1 1 64 ${64 - INNER} Z`}
            clipRule="evenodd"
          />
        </clipPath>
      </defs>
      <g clipPath={`url(#band-${key})`}>
        {second ? (
          <>
            <rect x="0" y="0" width="64" height="128" fill={first} />
            <rect x="64" y="0" width="64" height="128" fill={second} />
          </>
        ) : (
          <rect x="0" y="0" width="128" height="128" fill={first} />
        )}
        <rect x="0" y="0" width="128" height="128" fill={`url(#sheen-${key})`} />
      </g>
      {second ? (
        <g stroke="#0D0D10" strokeWidth="1.6" opacity="0.45">
          <path d={`M64 ${64 - OUTER} L64 ${64 - INNER}`} />
          <path d={`M64 ${64 + INNER} L64 ${64 + OUTER}`} />
        </g>
      ) : null}
      <circle cx="64" cy="64" r={INNER} fill="none" stroke="#0D0D10" strokeWidth="1.8" />
      <circle cx="64" cy="64" r={OUTER} fill="none" stroke="#0D0D10" strokeWidth="1.4" />
    </svg>
  );
};
