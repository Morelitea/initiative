/**
 * The two decorations that carry a year.
 *
 * Everything else in the catalog is a file, drawn once and served as an image.
 * These two say what year somebody finished, and an `<img>` cannot be told what
 * to be — so they are built here instead, with the year written in, and handed
 * out as data URIs. That keeps them a `src` like every other decoration, so
 * nothing that draws a banner or a trophy has to know which kind it is holding.
 *
 * The year is the wearer's, not the clock's: somebody who finished in 2014 is
 * still a 2014 grad next January. The picker offers this year because that is
 * the year most people setting it will want.
 */

/** The two ids that take a year. Mirrored by ``DATED_DECORATIONS`` on the server. */
export const GRAD_BANNER = "education.gradbanner";
export const GRAD_TROPHY = "education.gradtrophy";
export const DATED_DECORATIONS: ReadonlySet<string> = new Set([GRAD_BANNER, GRAD_TROPHY]);

/** The bounds the server keeps, so the picker cannot offer a year it will refuse. */
export const MIN_GRAD_YEAR = 1900;
export const GRAD_YEARS_AHEAD = 10;

export const currentYear = (): number => new Date().getFullYear();
export const maxGradYear = (): number => currentYear() + GRAD_YEARS_AHEAD;

/** A year to draw, whatever arrived: out of range or missing falls back to now. */
const usable = (year: number | null | undefined): number => {
  const value = Math.trunc(Number(year));
  return Number.isFinite(value) && value >= MIN_GRAD_YEAR && value <= maxGradYear()
    ? value
    : currentYear();
};

// No web font can load inside an SVG served as an image, so this is a stack of
// faces a machine already has, in the order they read best at four digits.
const SERIF = "Georgia, 'Times New Roman', 'Noto Serif', 'DejaVu Serif', serif";

const CONFETTI = [
  [18, 7, "#E8B84B", 24],
  [34, 22, "#D9534F", -12],
  [52, 5, "#7FBF46", 40],
  [68, 27, "#3E8ED0", -30],
  [96, 6, "#B45FC0", 16],
  [112, 24, "#E8B84B", -44],
  [128, 9, "#D9534F", 32],
  [146, 20, "#3E8ED0", -18],
  [8, 28, "#7FBF46", 8],
  [154, 6, "#B45FC0", -36],
] as const;

const bannerSvg = (year: number) => `<svg xmlns="http://www.w3.org/2000/svg"
  viewBox="0 0 160 40" width="1600" height="400" role="presentation"
  preserveAspectRatio="xMidYMid slice">
  <title>Grad</title>
  <defs>
    <linearGradient id="gbField" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#0F1A2E"/><stop offset="55%" stop-color="#1C2B4A"/>
      <stop offset="100%" stop-color="#132038"/>
    </linearGradient>
    <radialGradient id="gbLight" cx=".5" cy=".5" r=".55">
      <stop offset="0%" stop-color="#4E6EA8" stop-opacity=".45"/>
      <stop offset="100%" stop-color="#4E6EA8" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <style>
    .cf { animation: gbFall 9s linear infinite }
    .c1 { animation-duration: 12s; animation-delay: -3s }
    .c2 { animation-duration: 7.5s; animation-delay: -5s }
    .c3 { animation-duration: 10.5s; animation-delay: -7s }
    @keyframes gbFall { 0% { opacity: 0; transform: translateY(-5px) }
                        20% { opacity: .9 } 80% { opacity: .9 }
                        100% { opacity: 0; transform: translateY(12px) } }
    @media (prefers-reduced-motion: reduce) { .cf { animation: none; opacity: .7 } }
  </style>
  <rect width="160" height="40" fill="url(#gbField)"/>
  <ellipse cx="80" cy="20" rx="64" ry="22" fill="url(#gbLight)"/>
  ${CONFETTI.map(
    ([x, y, colour, angle], index) =>
      `<rect class="cf c${index % 4}" x="${x}" y="${y}" width="1.6" height="1" rx=".2"
        fill="${colour}" transform="rotate(${angle} ${x} ${y})"/>`
  ).join("")}
  <g fill="none" stroke="#E8B84B" opacity=".85">
    <path d="M6 6.4 L154 6.4" stroke-width=".9"/><path d="M6 8.4 L154 8.4" stroke-width=".5"/>
    <path d="M6 33.6 L154 33.6" stroke-width=".9"/><path d="M6 31.6 L154 31.6" stroke-width=".5"/>
  </g>
  <g fill="#3D4E78">
    <path d="M26 15.6 L36 19.6 L26 23.6 L16 19.6 Z"/>
    <path d="M20.4 21.8 L20.4 25.2 C20.4 26.4 22.8 27.2 26 27.2 C29.2 27.2 31.6 26.4 31.6 25.2
             L31.6 21.8 L26 24 Z"/>
    <path d="M134 15.6 L144 19.6 L134 23.6 L124 19.6 Z"/>
    <path d="M128.4 21.8 L128.4 25.2 C128.4 26.4 130.8 27.2 134 27.2 C137.2 27.2 139.6 26.4 139.6 25.2
             L139.6 21.8 L134 24 Z"/>
  </g>
  <g fill="#E8B84B">
    <circle cx="26" cy="19.6" r="1.3"/><circle cx="134" cy="19.6" r="1.3"/>
    <path d="M26 19.6 L33.4 22.6 L33.4 28" stroke="#E8B84B" stroke-width=".9" fill="none"
          stroke-linecap="round"/>
    <path d="M134 19.6 L141.4 22.6 L141.4 28" stroke="#E8B84B" stroke-width=".9" fill="none"
          stroke-linecap="round"/>
  </g>
  <text x="80" y="27.4" text-anchor="middle" font-family="${SERIF}" font-size="16.4"
        font-weight="bold" fill="#F6ECD2" letter-spacing="1.2">${year}</text>
  <text x="80" y="13" text-anchor="middle" font-family="${SERIF}" font-size="6.4"
        fill="#E8B84B" letter-spacing="4.4">GRAD</text>
</svg>`;

const trophySvg = (year: number) => `<svg xmlns="http://www.w3.org/2000/svg"
  viewBox="0 0 48 48" width="48" height="48" role="presentation">
  <title>Grad year</title>
  <circle cx="24" cy="24" r="23" fill="#16233A"/>
  <circle cx="24" cy="24" r="21" fill="none" stroke="#E8B84B" stroke-width="2"/>
  <g fill="#3D4E78">
    <path d="M24 8.6 L36 13.4 L24 18.2 L12 13.4 Z"/>
    <path d="M17.4 16 L17.4 19.6 C17.4 21 20.4 21.8 24 21.8 C27.6 21.8 30.6 21 30.6 19.6
             L30.6 16 L24 18.6 Z"/>
  </g>
  <circle cx="24" cy="13.4" r="1.5" fill="#E8B84B"/>
  <text x="24" y="33" text-anchor="middle" font-family="${SERIF}" font-size="12.4"
        font-weight="bold" fill="#F6ECD2" letter-spacing=".4">${year}</text>
  <text x="24" y="39.6" text-anchor="middle" font-family="${SERIF}" font-size="4.6"
        fill="#E8B84B" letter-spacing="2">GRAD</text>
</svg>`;

// Parentheses and apostrophes survive `encodeURIComponent`, and both of them
// end an unquoted CSS `url()` early — which is how half these are drawn.
const CSS_UNSAFE = /['()]/g;
const ESCAPED: Record<string, string> = { "'": "%27", "(": "%28", ")": "%29" };

const encode = (svg: string) =>
  `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg.replace(/\s+/g, " ").trim()).replace(
    CSS_UNSAFE,
    (character) => ESCAPED[character]
  )}`;

/** The artwork for a dated decoration, or nothing if the id does not take a year. */
export const gradArtwork = (id: string, year?: number | null): string | undefined => {
  if (id === GRAD_BANNER) return encode(bannerSvg(usable(year)));
  if (id === GRAD_TROPHY) return encode(trophySvg(usable(year)));
  return undefined;
};
