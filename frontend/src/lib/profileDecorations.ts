/**
 * The catalog a profile's decorations are resolved against.
 *
 * A profile stores **ids**, never images: `{ banner: "core.aurora", frame:
 * "core.gold", badges: ["core.founder"] }`. This module is what turns one of
 * those ids into something to render — a lookup in the table below, so an id
 * that isn't in it resolves to nothing at all.
 *
 * Everything here ships with the app under `public/decorations/`, so wearing a
 * banner costs a community none of its upload allowance. Which of them an
 * account may wear is the server's answer, not this file's — this only says
 * what a decoration looks like once it has been granted.
 *
 * Banners and frames animate; badges do not. A badge is a small, still mark of
 * belonging, and a row of them beside a name would be unreadable if each one
 * moved. The artwork is SVG rather than GIF so it stays crisp at any size,
 * weighs a few kB, and can hold still for a reader who has asked for less
 * motion — which it does, via `prefers-reduced-motion` inside each file.
 *
 * An id a deployment doesn't know renders as bare — which is the behaviour that
 * lets a profile keep wearing something the store has stopped offering.
 */

import type { ProfileDecorationsOutput } from "@/api/generated/initiativeAPI.schemas";

export type DecorationKind = "banner" | "frame" | "badge";

/**
 * Where a frame's artwork holds the picture, in its own 128-unit viewBox.
 *
 * Every frame is drawn to this one aperture: a circle of radius 50 at the
 * centre, which the picture fills exactly. A frame is then free to run outward
 * as far as the canvas allows — the gold ring is thin, the vinyl record is
 * thick — without either of them needing the code to know which it is.
 *
 * Sizing the artwork so radius 50 lands on the picture's edge makes it 128/50
 * as wide as the picture; the overhang splits evenly across the two sides,
 * which is what `FRAME_INSET` says in the units CSS wants.
 */
const FRAME_APERTURE = 50;
const FRAME_VIEWBOX = 128;

/**
 * How wide the artwork runs next to the picture it holds, and how far it hangs
 * off each side. Both are percentages of the picture's own box.
 *
 * The size has to be stated: an absolutely positioned `<img>` whose width is
 * `auto` is laid out at its intrinsic size no matter what its insets say, so
 * offsets alone would draw every frame at 128px whatever it surrounds.
 */
export const FRAME_SIZE = `${((FRAME_VIEWBOX / (FRAME_APERTURE * 2)) * 100).toFixed(2)}%`;
export const FRAME_INSET = `${(((1 - FRAME_VIEWBOX / 2 / FRAME_APERTURE) / 2) * 100).toFixed(2)}%`;

/**
 * The other way round: where the picture sits when the *artwork* is the thing
 * being sized. Used by the swatches, which show a frame at a fixed size with a
 * stand-in disc where a face would be.
 */
export const FRAME_APERTURE_INSET = `${(((1 - (FRAME_APERTURE * 2) / FRAME_VIEWBOX) / 2) * 100).toFixed(2)}%`;

/** Every decoration this build ships, by the name its label is keyed under. */
type DecorationName =
  | "aurora"
  | "ember"
  | "parchment"
  | "gold"
  | "arcane"
  | "fan"
  | "dicetower"
  | "natural20"
  | "d20"
  | "soundcheck"
  | "vinyl"
  | "cassette"
  | "observatory"
  | "orbital"
  | "flask"
  | "grove"
  | "overgrown"
  | "morel"
  | "hollow"
  | "cobweb"
  | "lantern"
  | "parade"
  | "spectrum"
  | "prideheart"
  | "floodlights"
  | "panels"
  | "matchball"
  | "endzone"
  | "laces"
  | "pigskin"
  | "rink"
  | "faceoff"
  | "puck"
  | "diamond"
  | "stitching"
  | "fastball"
  | "beach"
  | "net"
  | "spike"
  | "clay"
  | "strings"
  | "ace"
  | "dojo"
  | "blackbelt"
  | "beltknot"
  | "piste"
  | "blade"
  | "engarde"
  | "court"
  | "seams"
  | "swish";

/**
 * A pack is a marketplace listing now, so its name, publisher and description
 * come from the catalog — this file only says what its *pieces* look like.
 * That is why there is no pack table here: a pack published tomorrow needs no
 * entry, only artwork for the ids it grants.
 */

export interface Decoration {
  id: string;
  kind: DecorationKind;
  /**
   * For a banner, whether the artwork is dark enough to write on in white.
   *
   * A community picks its banner's text colour because it picks the picture.
   * A decoration's artwork ships with the app, so the artwork answers instead
   * — there is nothing to compute it from at runtime, and every banner but the
   * parchment one is a night sky.
   */
  ink?: "light" | "dark";
  /** Where the artwork is, relative to the app's root. */
  src: string;
  /** Key into the `profiles` namespace for this decoration's name. */
  labelKey: `decorations.${DecorationName}`;
}

const entry = (
  id: string,
  kind: DecorationKind,
  file: string,
  name: DecorationName,
  ink: "light" | "dark" = "light"
): Decoration => ({
  id,
  kind,
  src: `/decorations/${kind}s/${file}.svg`,
  labelKey: `decorations.${name}`,
  ...(kind === "banner" ? { ink } : null),
});

/** The catalog, by id. */
export const DECORATIONS: Readonly<Record<string, Decoration>> = {
  "core.aurora": entry("core.aurora", "banner", "core-aurora", "aurora"),
  "core.ember": entry("core.ember", "banner", "core-ember", "ember"),
  // The one banner that is not a night sky.
  "core.parchment": entry("core.parchment", "banner", "core-parchment", "parchment", "dark"),
  "core.gold": entry("core.gold", "frame", "core-gold", "gold"),
  "core.arcane": entry("core.arcane", "frame", "core-arcane", "arcane"),
  // The one badge nobody acquires: Initiative's own mark, for being here.
  "core.fan": entry("core.fan", "badge", "core-fan", "fan"),

  // Tabletop. The badge is the die the app already rolls when you finish
  // something, held still.
  "ttrpg.dicetower": entry("ttrpg.dicetower", "banner", "ttrpg-dicetower", "dicetower"),
  "ttrpg.natural20": entry("ttrpg.natural20", "frame", "ttrpg-natural20", "natural20"),
  "ttrpg.d20": entry("ttrpg.d20", "badge", "ttrpg-d20", "d20"),

  // Bands, choirs, anyone who books a room and plugs in.
  "music.soundcheck": entry("music.soundcheck", "banner", "music-soundcheck", "soundcheck"),
  "music.vinyl": entry("music.vinyl", "frame", "music-vinyl", "vinyl"),
  "music.cassette": entry("music.cassette", "badge", "music-cassette", "cassette"),

  // Labs, field stations, reading groups with a whiteboard.
  "science.observatory": entry(
    "science.observatory",
    "banner",
    "science-observatory",
    "observatory"
  ),
  "science.orbital": entry("science.orbital", "frame", "science-orbital", "orbital"),
  "science.flask": entry("science.flask", "badge", "science-flask", "flask"),

  // Foragers, mycologists, and anyone who stops a walk to look at a log.
  "fungi.grove": entry("fungi.grove", "banner", "fungi-grove", "grove"),
  "fungi.overgrown": entry("fungi.overgrown", "frame", "fungi-overgrown", "overgrown"),
  "fungi.morel": entry("fungi.morel", "badge", "fungi-morel", "morel"),

  // The group that keeps October in the calendar all year.
  "spooky.hollow": entry("spooky.hollow", "banner", "spooky-hollow", "hollow"),
  "spooky.web": entry("spooky.web", "frame", "spooky-web", "cobweb"),
  "spooky.lantern": entry("spooky.lantern", "badge", "spooky-lantern", "lantern"),

  "pride.parade": entry("pride.parade", "banner", "pride-parade", "parade"),
  "pride.spectrum": entry("pride.spectrum", "frame", "pride-spectrum", "spectrum"),
  "pride.heart": entry("pride.heart", "badge", "pride-heart", "prideheart"),

  // Clubs, leagues, five-a-side regulars, and the group chat that only wakes
  // up on a matchday. Eight sports, one shape each: the field it is played on,
  // a frame made of the equipment, and the object itself.
  "soccer.floodlights": entry("soccer.floodlights", "banner", "soccer-floodlights", "floodlights"),
  "soccer.panels": entry("soccer.panels", "frame", "soccer-panels", "panels"),
  "soccer.matchball": entry("soccer.matchball", "badge", "soccer-matchball", "matchball"),

  "hoops.court": entry("hoops.court", "banner", "hoops-court", "court"),
  "hoops.seams": entry("hoops.seams", "frame", "hoops-seams", "seams"),
  "hoops.swish": entry("hoops.swish", "badge", "hoops-swish", "swish"),

  "gridiron.endzone": entry("gridiron.endzone", "banner", "gridiron-endzone", "endzone"),
  "gridiron.laces": entry("gridiron.laces", "frame", "gridiron-laces", "laces"),
  "gridiron.pigskin": entry("gridiron.pigskin", "badge", "gridiron-pigskin", "pigskin"),

  "hockey.rink": entry("hockey.rink", "banner", "hockey-rink", "rink"),
  "hockey.faceoff": entry("hockey.faceoff", "frame", "hockey-faceoff", "faceoff"),
  "hockey.puck": entry("hockey.puck", "badge", "hockey-puck", "puck"),

  "baseball.diamond": entry("baseball.diamond", "banner", "baseball-diamond", "diamond"),
  "baseball.stitching": entry("baseball.stitching", "frame", "baseball-stitching", "stitching"),
  "baseball.fastball": entry("baseball.fastball", "badge", "baseball-fastball", "fastball"),

  "volleyball.beach": entry("volleyball.beach", "banner", "volleyball-beach", "beach"),
  "volleyball.net": entry("volleyball.net", "frame", "volleyball-net", "net"),
  "volleyball.spike": entry("volleyball.spike", "badge", "volleyball-spike", "spike"),

  // The one court that is not green or blue, which is what makes it read.
  "tennis.clay": entry("tennis.clay", "banner", "tennis-clay", "clay", "dark"),
  "tennis.strings": entry("tennis.strings", "frame", "tennis-strings", "strings"),
  "tennis.ace": entry("tennis.ace", "badge", "tennis-ace", "ace"),

  "dojo.hall": entry("dojo.hall", "banner", "dojo-hall", "dojo"),
  "dojo.blackbelt": entry("dojo.blackbelt", "frame", "dojo-blackbelt", "blackbelt"),
  "dojo.beltknot": entry("dojo.beltknot", "badge", "dojo-beltknot", "beltknot"),

  "fencing.piste": entry("fencing.piste", "banner", "fencing-piste", "piste"),
  "fencing.blade": entry("fencing.blade", "frame", "fencing-blade", "blade"),
  "fencing.engarde": entry("fencing.engarde", "badge", "fencing-engarde", "engarde"),
};

/** The decoration this id names, if this build has it and it is of that kind. */
export const resolveDecoration = (
  id: string | null | undefined,
  kind: DecorationKind
): Decoration | undefined => {
  if (!id) return undefined;
  const found = DECORATIONS[id];
  return found?.kind === kind ? found : undefined;
};

/** The badges a profile is wearing that this build can draw, in the order worn. */
export const resolveBadges = (
  decorations: ProfileDecorationsOutput | null | undefined
): Decoration[] =>
  (decorations?.badges ?? [])
    .map((id) => resolveDecoration(id, "badge"))
    .filter((badge): badge is Decoration => Boolean(badge));
