// Draw Chester's poses from his line art.
//
//   node scripts/build-chester.mjs
//
// src/assets/chester/base.svg is the drawing, as Affinity exports it: one
// group per part (ears, antlers, face, mouth, nose, eyes, leaf body, stem
// tail). This flattens each part's transforms into its paths and writes one
// animated SVG per pose beside it, adding what the pose needs on top: closed
// or happy eyes, an open mouth, sparkles, thought dots. Edit base.svg or this
// file, never the poses, and run it again.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const DIR = join(dirname(fileURLToPath(import.meta.url)), "../src/assets/chester");

// The artboard is 2953 units square; the poses draw it at a tenth of that.
// At 64px the whole figure leaves his face too small to read, so the frame
// holds his head, ears and antlers, with room for the hop and the ear swings,
// and the leaf body runs off the bottom edge.
const SCALE = 0.1;
const VIEW_BOX = "47 -17 205 205";

const INK = "#2B1A10";
const CREAM = "#FEFAE0";
const PINK = "#E79AA2";
const GOLD = "#F6C85C";
const HALO = "#F4EBDD";

// --- Reading the drawing -----------------------------------------------------

const parseSvg = (source) => {
  const root = { name: "root", attrs: {}, children: [] };
  const stack = [root];
  for (const [tag] of source.matchAll(
    /<!--[\s\S]*?-->|<\?[\s\S]*?\?>|<!DOCTYPE[^>]*>|<\/?[^>]+>/g
  )) {
    if (/^<[!?]/.test(tag)) continue;
    if (tag.startsWith("</")) {
      stack.pop();
      continue;
    }
    const attrs = {};
    for (const [, key, value] of tag.matchAll(/([\w:-]+)="([^"]*)"/g)) attrs[key] = value;
    const el = { name: tag.match(/^<([\w:-]+)/)[1], attrs, children: [] };
    stack.at(-1).children.push(el);
    if (!tag.endsWith("/>")) stack.push(el);
  }
  return root;
};

const multiply = (m, n) => [
  m[0] * n[0] + m[2] * n[1],
  m[1] * n[0] + m[3] * n[1],
  m[0] * n[2] + m[2] * n[3],
  m[1] * n[2] + m[3] * n[3],
  m[0] * n[4] + m[2] * n[5] + m[4],
  m[1] * n[4] + m[3] * n[5] + m[5],
];

const IDENTITY = [1, 0, 0, 1, 0, 0];

const parseTransform = (transform) => {
  if (!transform) return IDENTITY;
  const matrix = transform.match(/^matrix\(([^)]*)\)$/);
  if (!matrix) throw new Error(`build-chester: unsupported transform ${transform}`);
  return matrix[1].split(",").map(Number);
};

const round = (n) => String(Math.round(n * 10) / 10);

// Affinity writes absolute M, C, L and Z only, so every number is half of an
// x,y pair and an affine transform maps the curve exactly.
const transformPath = (d, m) => {
  if (/[^MCLZ\d\s,.-]/.test(d))
    throw new Error("build-chester: path uses a command besides M C L Z");
  return d
    .replace(/(-?[\d.]+),(-?[\d.]+)/g, (_, xs, ys) => {
      const [x, y] = [Number(xs), Number(ys)];
      return `${round((m[0] * x + m[2] * y + m[4]) * SCALE)} ${round((m[1] * x + m[3] * y + m[5]) * SCALE)}`;
    })
    .replace(/\s*([MCLZ])\s*/g, "$1")
    .replace(/ -/g, "-");
};

/** Every path of the drawing, keyed by the top-level part it belongs to. */
const readParts = () => {
  const parts = new Map();
  const clips = new Map();
  const walk = (el, ctm, part, clip) => {
    const m = multiply(ctm, parseTransform(el.attrs.transform));
    if (el.name === "rect") return;
    if (el.name === "path") {
      const fill = (el.attrs.style ?? "").match(/fill:rgb\((\d+),(\d+),(\d+)\)/);
      const hex = fill
        ? `#${fill
            .slice(1)
            .map((c) => Number(c).toString(16).padStart(2, "0"))
            .join("")
            .toUpperCase()}`
        : null;
      const path = { d: transformPath(el.attrs.d, m), fill: hex, clip };
      if (el.inClip) clips.set(el.inClip, [...(clips.get(el.inClip) ?? []), path]);
      else parts.set(part, [...(parts.get(part) ?? []), path]);
      return;
    }
    if (el.name === "clipPath") {
      for (const child of el.children) {
        child.inClip = el.attrs.id;
        walk(child, m, part, clip);
      }
      return;
    }
    const id = el.attrs.id;
    const nextPart = part ?? (id && !id.startsWith("Artboard") ? id : null);
    const nextClip = el.attrs["clip-path"]?.match(/#([^)]+)/)?.[1] ?? clip;
    for (const child of el.children) walk(child, m, nextPart, nextClip);
  };
  walk(parseSvg(readFileSync(join(DIR, "base.svg"), "utf8")), IDENTITY, null, null);
  return { parts, clips };
};

const { parts, clips } = readParts();

const EXPECTED = [
  "ear-right",
  "ear-left",
  "antlers",
  "face",
  "mouth",
  "nose",
  "eye-left",
  "eye-right",
  "leaf-body",
  "stem-tail",
];
for (const id of EXPECTED) {
  if (!parts.has(id)) throw new Error(`build-chester: base.svg has no #${id}`);
}

const paths = (list) =>
  list
    .map(
      ({ d, fill, clip }) =>
        `<path d="${d}"${fill ? ` fill="${fill}"` : ""}${clip ? ` clip-path="url(#${clip})"` : ""}/>`
    )
    .join("\n");

const part = (id) => paths(parts.get(id));

// The brown line between the muzzle's lips; an open mouth goes under it.
const LIP = "#8C5A38";
const mouthPaths = parts.get("mouth");
const lipIndex = mouthPaths.findLastIndex((p) => p.fill === LIP);
if (lipIndex < 0) throw new Error(`build-chester: #mouth has no ${LIP} lip line`);

// The chin under the lip line: the mouth's lowest path besides the line.
const lowest = (d) => Math.max(...[...d.matchAll(/-?[\d.]+ (-?[\d.]+)/g)].map((m) => Number(m[1])));
const jaw = mouthPaths
  .filter((_, i) => i !== lipIndex)
  .reduce((a, b) => (lowest(b.d) > lowest(a.d) ? b : a));

const clipDefs = [...clips]
  .map(
    ([id, list]) =>
      `<clipPath id="${id}">${list.map(({ d }) => `<path d="${d}"/>`).join("")}</clipPath>`
  )
  .join("\n");

// --- What the poses add ------------------------------------------------------
// Drawn in the poses' units, against the face as base.svg places it: the near
// eye (viewer's left) sits around 135,100 and the far eye around 170,95.

const shape = (d, fill = INK) => `<path d="${d}" fill="${fill}"/>`;

/** Eyes shut, the lids' line bowing down. */
const SHUT = [
  shape("M124.5 97C130 102 139 104 146.5 102.5C139 107.5 129 106.5 124.5 97Z"),
  shape("M165 95C167.5 98.5 171.5 98.5 174.5 93.5C172 102 166.5 102 165 95Z"),
];

/** Eyes closed in a smile, bowing up. */
const HAPPY = [
  shape("M124.5 102.5C129 94.5 140 93.5 146.5 101C140 98 130 99 124.5 102.5Z"),
  shape("M165 98.5C166.5 91.5 172 90.5 174.5 95.5C172 95 168 95.5 165 98.5Z"),
];

// An open mouth hangs from the lip line: its top edge runs along the middle
// of that line from corner to corner, through the notch under the nose at
// 164.9,137, and the line is drawn back over it as the upper lip. The jaw
// (the chin under the line) stretches down by `stretch` from the mouth's
// corners at y 139.5, so its ends stay put, and the opening stops just inside
// it, leaving a rim of chin below.
const LIP_LINE =
  "M147.2 140.9C151 142.3 154.8 142.9 157.4 142.5C161 141.9 163.6 139.2 164.9 137C166.2 138.9 168.6 140.1 171 140.3C172 140.4 172.8 140.4 173.6 140.3";

const openMouth = (stretch) => {
  const corners = 139.5;
  const jawDrop = `matrix(1 0 0 ${stretch} 0 ${round(corners * (1 - stretch))})`;
  const y = (n) => round(corners + (n - corners) * stretch);
  return [
    `<path d="${jaw.d}" fill="${jaw.fill}" transform="${jawDrop}"/>`,
    shape(
      `${LIP_LINE}C171.8 ${y(144.6)} 161.5 ${y(148)} 149 ${y(144)}C148.2 ${y(143.3)} 147.6 ${y(142.2)} 147.2 140.9Z`
    ),
    `<path d="M153.8 143.8C157 142.3 165 142 169.2 142.9C167 144.4 163 145.3 159 145.1C156.8 145 155 144.6 153.8 143.8Z" fill="${PINK}" transform="${jawDrop}"/>`,
  ];
};

const MOUTH_OPEN = openMouth(1.12);
const MOUTH_WIDE = openMouth(1.3);

/** A four-pointed sparkle centred on cx,cy. */
const sparkle = (cx, cy, r) => {
  const k = r * 0.2;
  const at = (x, y) => `${round(cx + x)} ${round(cy + y)}`;
  return `<path class="sparkle" d="M${at(0, -r)}Q${at(k, -k)} ${at(r, 0)}Q${at(k, k)} ${at(0, r)}Q${at(-k, k)} ${at(-r, 0)}Q${at(-k, -k)} ${at(0, -r)}Z" fill="${GOLD}" stroke="${INK}" stroke-width="2.6" stroke-linejoin="round"/>`;
};

const SPARKLE_GROUP = `<g>${[sparkle(88, 128, 10), sparkle(214, 112, 13), sparkle(232, 150, 7)].join("")}</g>`;

const dot = (cx, cy, r) =>
  `<circle class="dot" cx="${cx}" cy="${cy}" r="${r}" fill="${CREAM}" stroke="${INK}" stroke-width="2.4"/>`;

// --- Movement ----------------------------------------------------------------
// Pivots, in the poses' units: the figure stands on the bottom of the leaf,
// the head turns where it meets the leaf and each ear swings from its root.
// The swings are kept short enough that nothing leaves the frame.

const BASE_CSS = `
.fig { transform-origin: 155px 292px; }
.head { transform-origin: 158px 150px; }
.ear-l { transform-origin: 122px 90px; }
.ear-r { transform-origin: 178px 84px; }
.shut, .alt { opacity: 0; }`;

const BLINK = `
.open { animation: open 4s linear infinite; }
.shut { animation: shut 4s linear infinite; }
@keyframes open { 0%, 92%, 98%, 100% { opacity: 1; } 93%, 97% { opacity: 0; } }
@keyframes shut { 0%, 92%, 98%, 100% { opacity: 0; } 93%, 97% { opacity: 1; } }`;

const BOUNCE = `
@keyframes bounce { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-4.5px); } }`;

const TWITCH = `
@keyframes twitch { 0%, 80%, 100% { transform: rotate(0deg); } 85% { transform: rotate(5deg); } 90% { transform: rotate(-2deg); } }`;

const SPARKLE = (seconds) => `
.sparkle { animation: sparkle ${seconds}s ease-in-out infinite; transform-box: fill-box; transform-origin: center; }
.sparkle:nth-of-type(2) { animation-delay: -${seconds / 3}s; }
.sparkle:nth-of-type(3) { animation-delay: -${(seconds * 2) / 3}s; }
@keyframes sparkle { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.35; transform: scale(0.7); } }`;

/**
 * One pose: the drawing in its moving groups, and what the pose adds.
 *
 * `eyes` replaces the open eyes for the whole pose; `blink` draws a closed
 * pair over them that the CSS shows briefly; `winkEye` closes only the near
 * eye; `mouth` and `altMouth` open the mouth under the lip line.
 */
const pose = ({ css, eyes, blink, winkEye, mouth = [], altMouth = [], extras = "" }) => {
  const nearEye = part("eye-left");
  const farEye = part("eye-right");
  let eyeLayer;
  if (eyes) eyeLayer = eyes.join("\n");
  else if (winkEye)
    eyeLayer = `<g class="open">${nearEye}</g>\n<g class="shut">${winkEye}</g>\n${farEye}`;
  else if (blink)
    eyeLayer = `<g class="open">${nearEye}\n${farEye}</g>\n<g class="shut">${blink.join("\n")}</g>`;
  else eyeLayer = `${nearEye}\n${farEye}`;

  const mouthLayer = [
    mouth.length ? `<g class="mouth">${mouth.join("\n")}</g>` : "",
    altMouth.length ? `<g class="alt">${altMouth.join("\n")}</g>` : "",
  ]
    .filter(Boolean)
    .join("\n");

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${VIEW_BOX}">
<!-- Drawn by frontend/scripts/build-chester.mjs from base.svg; edit those and run it again. -->
<style>${BASE_CSS}${css}
@media (prefers-reduced-motion: reduce) { * { animation: none !important; } }
</style>
<defs>
<filter id="halo" filterUnits="userSpaceOnUse" x="-20" y="-30" width="350" height="350">
<feGaussianBlur in="SourceAlpha" stdDeviation="5"/>
<feComponentTransfer result="edge"><feFuncA type="linear" slope="100" intercept="-2.5"/></feComponentTransfer>
<feFlood flood-color="${HALO}"/>
<feComposite in2="edge" operator="in"/>
<feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
</filter>
${clipDefs}
</defs>
<g filter="url(#halo)">
<g class="fig">
<g class="head">
<g class="ear-r">${part("ear-right")}</g>
<g class="ear-l">${part("ear-left")}</g>
${part("antlers")}
${part("face")}
${paths(mouthPaths.filter((_, i) => i !== lipIndex))}
${mouthLayer}
${paths([mouthPaths[lipIndex]])}
${part("nose")}
${eyeLayer}
</g>
${part("leaf-body")}
${part("stem-tail")}
${extras}
</g>
</g>
</svg>
`;
};

const POSES = {
  idle: pose({
    css: `
.fig { animation: bounce 2.4s ease-in-out infinite; }
.head { animation: bob 2.4s ease-in-out 0.2s infinite; }
.ear-r { animation: twitch 5s ease-in-out infinite; }
@keyframes bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-2.5px); } }${BOUNCE}${TWITCH}${BLINK}`,
    blink: SHUT,
  }),

  excited: pose({
    css: `
.fig { animation: hop 0.6s ease-in-out infinite; }
.ear-l, .ear-r { animation: flick 0.3s ease-in-out infinite; }
.ear-l { animation-direction: reverse; }
@keyframes hop { 0%, 100% { transform: translateY(0) scale(1.03, 0.96); } 15% { transform: translateY(-4.5px) scale(0.98, 1.03); } 50% { transform: translateY(-12px) scale(1, 1); } 85% { transform: translateY(-3px) scale(0.99, 1.02); } }
@keyframes flick { 0%, 100% { transform: rotate(-2deg); } 50% { transform: rotate(4deg); } }${SPARKLE(0.6)}`,
    mouth: MOUTH_WIDE,
    extras: SPARKLE_GROUP,
  }),

  farewell: pose({
    css: `
.fig { animation: bounce 2.4s ease-in-out infinite; }
.head { animation: sway 1.4s ease-in-out infinite; }
.ear-r { animation: wave 0.6s ease-in-out infinite; }
@keyframes sway { 0%, 100% { transform: rotate(-2deg); } 50% { transform: rotate(1.5deg); } }
@keyframes wave { 0%, 100% { transform: rotate(-8deg); } 50% { transform: rotate(4deg); } }${BOUNCE}${BLINK}`,
    blink: SHUT,
  }),

  proud: pose({
    css: `
.fig { animation: bounce 2.4s ease-in-out infinite; }
.head { animation: chin 2.4s ease-in-out infinite; }
@keyframes chin { 0%, 100% { transform: rotate(-2deg) translateY(-2px); } 50% { transform: rotate(-3.5deg) translateY(-4.5px); } }${BOUNCE}${SPARKLE(1.2)}`,
    eyes: HAPPY,
    extras: SPARKLE_GROUP,
  }),

  talking: pose({
    css: `
.fig { animation: bounce 2.4s ease-in-out infinite; }
.head { animation: nod 1.2s ease-in-out infinite; }
.mouth { opacity: 0; animation: talk-a 0.6s linear infinite; }
.alt { animation: talk-b 0.6s linear infinite; }
@keyframes nod { 0%, 100% { transform: rotate(0deg); } 50% { transform: rotate(-3deg); } }
@keyframes talk-a { 0%, 32% { opacity: 1; } 33%, 100% { opacity: 0; } }
@keyframes talk-b { 0%, 32%, 67%, 100% { opacity: 0; } 33%, 66% { opacity: 1; } }${BOUNCE}${BLINK}`,
    blink: SHUT,
    mouth: MOUTH_OPEN,
    altMouth: MOUTH_WIDE,
  }),

  thinking: pose({
    css: `
.head { animation: tilt 3s ease-in-out infinite; }
.dot { animation: dots 1.5s ease-in-out infinite; }
.dot:nth-of-type(2) { animation-delay: 0.25s; }
.dot:nth-of-type(3) { animation-delay: 0.5s; }
@keyframes tilt { 0%, 100% { transform: rotate(0deg); } 50% { transform: rotate(-2.5deg); } }
@keyframes dots { 0%, 100% { opacity: 0.25; } 30%, 70% { opacity: 1; } }${BLINK}`,
    blink: SHUT,
    extras: `<g>${dot(206, 126, 3.2)}${dot(216, 109, 4.8)}${dot(230, 89, 6.8)}</g>`,
  }),

  winking: pose({
    css: `
.fig { animation: bounce 3s ease-in-out infinite; }
.head { animation: wink-head 3s ease-in-out infinite; }
.ear-r { animation: twitch 3s ease-in-out infinite; }
.open { animation: open 3s linear infinite; }
.shut { animation: wink 3s linear infinite; }
@keyframes wink-head { 0%, 20%, 85%, 100% { transform: rotate(0deg); } 28%, 75% { transform: rotate(-4deg); } }
@keyframes open { 0%, 22%, 82%, 100% { opacity: 1; } 25%, 78% { opacity: 0; } }
@keyframes wink { 0%, 22%, 82%, 100% { opacity: 0; } 25%, 78% { opacity: 1; } }${BOUNCE}${TWITCH}`,
    winkEye: HAPPY[0],
  }),
};

for (const [name, svg] of Object.entries(POSES)) {
  writeFileSync(join(DIR, `${name}.svg`), svg);
  console.log(`build-chester: ${name}.svg (${(svg.length / 1024).toFixed(1)} KB)`);
}
