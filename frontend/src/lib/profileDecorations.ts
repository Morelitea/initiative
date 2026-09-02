/**
 * The catalog a profile's decorations are resolved against.
 *
 * A profile stores **ids**, never images: `{ banner: "core.aurora", frame:
 * "core.gold", trophies: ["core.founder"] }`. This module is what turns one of
 * those ids into something to render — a lookup in the table below, so an id
 * that isn't in it resolves to nothing at all.
 *
 * Everything here ships with the app under `public/decorations/`, so wearing a
 * banner costs a community none of its upload allowance. Which of them an
 * account may wear is the server's answer, not this file's — this only says
 * what a decoration looks like once it has been granted.
 *
 * Banners and frames animate; trophies do not. A trophy is a small, still mark of
 * belonging, and a row of them beside a name would be unreadable if each one
 * moved. The artwork is SVG rather than GIF so it stays crisp at any size,
 * weighs a few kB, and can hold still for a reader who has asked for less
 * motion — which it does, via `prefers-reduced-motion` inside each file.
 *
 * An id a deployment doesn't know renders as bare — which is the behaviour that
 * lets a profile keep wearing something the store has stopped offering.
 */

import type { ProfileDecorationsOutput } from "@/api/generated/initiativeAPI.schemas";

export type DecorationKind = "banner" | "frame" | "trophy";

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
  | "ace"
  | "ammonite"
  | "amphitheatre"
  | "arcade"
  | "aurora"
  | "autistic"
  | "balcony"
  | "bat"
  | "bauble"
  | "beach"
  | "benzene"
  | "bi"
  | "bicycle"
  | "blade"
  | "blind"
  | "bones"
  | "bookshelf"
  | "braille"
  | "bunting"
  | "buttons"
  | "bytrain"
  | "caddies"
  | "campfire"
  | "car"
  | "cassette"
  | "cat"
  | "catnap"
  | "chronicpain"
  | "clapper"
  | "clay"
  | "cobweb"
  | "cocoa"
  | "collar"
  | "controller"
  | "court"
  | "cowries"
  | "crown"
  | "curtain"
  | "d20"
  | "dagger"
  | "deaf"
  | "desert"
  | "diabetes"
  | "diamond"
  | "dicetower"
  | "directorschair"
  | "disabilitypride"
  | "dividers"
  | "dna"
  | "dog"
  | "drivein"
  | "drums"
  | "ember"
  | "endzone"
  | "engarde"
  | "enso"
  | "faceoff"
  | "fan"
  | "fastball"
  | "feather"
  | "festival"
  | "fetch"
  | "filmstrip"
  | "fist"
  | "fivestripes"
  | "flagargentina"
  | "flagbrazil"
  | "flagchina"
  | "flagcolombia"
  | "flagcuba"
  | "flagegypt"
  | "flagethiopia"
  | "flagfrance"
  | "flagghana"
  | "flaggreece"
  | "flaghaiti"
  | "flagindia"
  | "flagindonesia"
  | "flagireland"
  | "flagitaly"
  | "flagjamaica"
  | "flagjapan"
  | "flagkenya"
  | "flagkorea"
  | "flaglebanon"
  | "flagmexico"
  | "flagmorocco"
  | "flagnigeria"
  | "flagpakistan"
  | "flagperu"
  | "flagphilippines"
  | "flagpoland"
  | "flagsamoa"
  | "flagsouthafrica"
  | "flagturkey"
  | "flagukraine"
  | "flagvietnam"
  | "flask"
  | "floodlights"
  | "fourdirections"
  | "garden"
  | "gay"
  | "ghost"
  | "glasses"
  | "globe"
  | "gold"
  | "grove"
  | "guitar"
  | "hamster"
  | "handprint"
  | "hearth"
  | "helix"
  | "hollow"
  | "horse"
  | "icicles"
  | "incense"
  | "ironwork"
  | "kente"
  | "keys"
  | "koi"
  | "labbench"
  | "laces"
  | "lake"
  | "landmarks"
  | "lantern"
  | "laurel"
  | "lesbian"
  | "lizard"
  | "lotus"
  | "magnet"
  | "marquee"
  | "masks"
  | "matcha"
  | "matchball"
  | "medicinewheel"
  | "mentalhealth"
  | "meridians"
  | "microphone"
  | "microscope"
  | "mobilityaid"
  | "monstera"
  | "morel"
  | "morningstar"
  | "mountain"
  | "natural20"
  | "nest"
  | "net"
  | "neurodivergent"
  | "nightsky"
  | "nonbinary"
  | "northstar"
  | "notebook"
  | "observatory"
  | "orbital"
  | "overgrown"
  | "pages"
  | "panafrican"
  | "panafricanflag"
  | "panels"
  | "parade"
  | "parchment"
  | "pawprint"
  | "pigskin"
  | "pines"
  | "piste"
  | "plane"
  | "playhouse"
  | "poly"
  | "popcorn"
  | "porcelain"
  | "prideheart"
  | "projector"
  | "puck"
  | "quill"
  | "rabbit"
  | "rakedsand"
  | "rakelines"
  | "rat"
  | "reel"
  | "ridge"
  | "rink"
  | "rockhammer"
  | "rosette"
  | "saxophone"
  | "screening"
  | "seams"
  | "servicedog"
  | "sheetmusic"
  | "ship"
  | "singingbowl"
  | "skeletons"
  | "snake"
  | "snowfall"
  | "snowflake"
  | "snowman"
  | "soundcheck"
  | "spectrum"
  | "spike"
  | "spines"
  | "split"
  | "spoon"
  | "stack"
  | "stacks"
  | "stage"
  | "stitching"
  | "stones"
  | "streetparty"
  | "strings"
  | "succulent"
  | "swish"
  | "teabag"
  | "teacup"
  | "teagarden"
  | "tealeaves"
  | "teapot"
  | "teaservice"
  | "tennisace"
  | "tent"
  | "ticket"
  | "train"
  | "trans"
  | "turntable"
  | "twospirit"
  | "typewriter"
  | "vines"
  | "vinyl"
  | "violin"
  | "weave"
  | "wheelchair"
  | "windowsill"
  | "witchinghour"
  | "wreath"
  | "writingdesk"
  | "yorick";

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
  /**
   * How many colours the wearer picks for this one, if they pick any.
   *
   * Only what ships with the app: a pack's artwork is the pack's, and a
   * publisher who wanted it recoloured would have shipped it that way. A frame
   * with this set is drawn by `TintedFrame` rather than served as a file — the
   * file at `src` is what it looks like in its default colours.
   */
  tint?: 1 | 2;
}

/** Where each slot's artwork lives, since one of them does not just take an s. */
const FOLDER: Record<DecorationKind, string> = {
  banner: "banners",
  frame: "frames",
  trophy: "trophies",
};

const entry = (
  id: string,
  kind: DecorationKind,
  file: string,
  name: DecorationName,
  ink: "light" | "dark" = "light"
): Decoration => ({
  id,
  kind,
  src: `/decorations/${FOLDER[kind]}/${file}.svg`,
  labelKey: `decorations.${name}`,
  ...(kind === "banner" ? { ink } : null),
  ...(id in DEFAULT_TINTS ? { tint: DEFAULT_TINTS[id].length as 1 | 2 } : null),
});

/**
 * The frames whose colour is the wearer's, and what they are before anybody
 * chooses. The length is how many colours the frame takes, which is why the
 * catalog reads its `tint` from here rather than repeating the number.
 */
export const DEFAULT_TINTS: Readonly<Record<string, readonly string[]>> = {
  "core.gold": ["#d4a017"],
  "core.split": ["#1b5e32", "#f2c230"],
};

/** The catalog, by id — the app's own first, then every theme in order. */
export const DECORATIONS: Readonly<Record<string, Decoration>> = {
  // What ships with the app, and belongs to no theme.
  "core.aurora": entry("core.aurora", "banner", "core-aurora", "aurora"),
  "core.ember": entry("core.ember", "banner", "core-ember", "ember"),
  "core.parchment": entry("core.parchment", "banner", "core-parchment", "parchment", "dark"),
  "core.gold": entry("core.gold", "frame", "core-gold", "gold"),
  "core.split": entry("core.split", "frame", "core-split", "split"),
  "core.fan": entry("core.fan", "trophy", "core-fan", "fan"),

  "baseball.diamond": entry("baseball.diamond", "banner", "baseball-diamond", "diamond"),
  "baseball.stitching": entry("baseball.stitching", "frame", "baseball-stitching", "stitching"),
  "baseball.fastball": entry("baseball.fastball", "trophy", "baseball-fastball", "fastball"),

  "books.desk": entry("books.desk", "banner", "books-desk", "writingdesk", "dark"),
  "books.shelf": entry("books.shelf", "banner", "books-shelf", "bookshelf", "dark"),
  "books.stacks": entry("books.stacks", "banner", "books-stacks", "stacks"),
  "books.pages": entry("books.pages", "frame", "books-pages", "pages"),
  "books.spines": entry("books.spines", "frame", "books-spines", "spines"),
  "books.glasses": entry("books.glasses", "trophy", "books-glasses", "glasses"),
  "books.notebook": entry("books.notebook", "trophy", "books-notebook", "notebook"),
  "books.quill": entry("books.quill", "trophy", "books-quill", "quill"),
  "books.stack": entry("books.stack", "trophy", "books-stack", "stack"),
  "books.typewriter": entry("books.typewriter", "trophy", "books-typewriter", "typewriter"),

  "cinema.drivein": entry("cinema.drivein", "banner", "cinema-drivein", "drivein"),
  "cinema.marquee": entry("cinema.marquee", "banner", "cinema-marquee", "marquee"),
  "cinema.screening": entry("cinema.screening", "banner", "cinema-screening", "screening"),
  "cinema.filmstrip": entry("cinema.filmstrip", "frame", "cinema-filmstrip", "filmstrip"),
  "cinema.reel": entry("cinema.reel", "frame", "cinema-reel", "reel"),
  "cinema.chair": entry("cinema.chair", "trophy", "cinema-chair", "directorschair"),
  "cinema.clapper": entry("cinema.clapper", "trophy", "cinema-clapper", "clapper"),
  "cinema.popcorn": entry("cinema.popcorn", "trophy", "cinema-popcorn", "popcorn"),
  "cinema.projector": entry("cinema.projector", "trophy", "cinema-projector", "projector"),
  "cinema.ticket": entry("cinema.ticket", "trophy", "cinema-ticket", "ticket"),

  // For the community, and for the things people in it are.
  "disability.pride": entry("disability.pride", "banner", "disability-pride", "disabilitypride"),
  "disability.braille": entry("disability.braille", "frame", "disability-braille", "braille"),
  "disability.stripes": entry("disability.stripes", "frame", "disability-stripes", "fivestripes"),
  "disability.autistic": entry("disability.autistic", "trophy", "disability-autistic", "autistic"),
  "disability.blind": entry("disability.blind", "trophy", "disability-blind", "blind"),
  "disability.chronicpain": entry(
    "disability.chronicpain",
    "trophy",
    "disability-chronicpain",
    "chronicpain"
  ),
  "disability.deaf": entry("disability.deaf", "trophy", "disability-deaf", "deaf"),
  "disability.diabetes": entry("disability.diabetes", "trophy", "disability-diabetes", "diabetes"),
  "disability.mentalhealth": entry(
    "disability.mentalhealth",
    "trophy",
    "disability-mentalhealth",
    "mentalhealth"
  ),
  "disability.mobility": entry(
    "disability.mobility",
    "trophy",
    "disability-mobility",
    "mobilityaid"
  ),
  "disability.neurodivergent": entry(
    "disability.neurodivergent",
    "trophy",
    "disability-neurodivergent",
    "neurodivergent"
  ),
  "disability.servicedog": entry(
    "disability.servicedog",
    "trophy",
    "disability-servicedog",
    "servicedog"
  ),
  "disability.spoon": entry("disability.spoon", "trophy", "disability-spoon", "spoon"),
  "disability.wheelchair": entry(
    "disability.wheelchair",
    "trophy",
    "disability-wheelchair",
    "wheelchair"
  ),

  "drama.amphitheatre": entry("drama.amphitheatre", "banner", "drama-amphitheatre", "amphitheatre"),
  "drama.playhouse": entry("drama.playhouse", "banner", "drama-playhouse", "playhouse"),
  "drama.stage": entry("drama.stage", "banner", "drama-stage", "stage"),
  "drama.curtain": entry("drama.curtain", "frame", "drama-curtain", "curtain"),
  "drama.laurel": entry("drama.laurel", "frame", "drama-laurel", "laurel"),
  "drama.balcony": entry("drama.balcony", "trophy", "drama-balcony", "balcony"),
  "drama.dagger": entry("drama.dagger", "trophy", "drama-dagger", "dagger"),
  "drama.masks": entry("drama.masks", "trophy", "drama-masks", "masks"),
  "drama.skull": entry("drama.skull", "trophy", "drama-skull", "yorick"),

  "fencing.piste": entry("fencing.piste", "banner", "fencing-piste", "piste"),
  "fencing.blade": entry("fencing.blade", "frame", "fencing-blade", "blade"),
  "fencing.engarde": entry("fencing.engarde", "trophy", "fencing-engarde", "engarde"),

  // Original work in these design traditions, not a copy of any nation's own.
  "firstnations.morningstar": entry(
    "firstnations.morningstar",
    "banner",
    "firstnations-morningstar",
    "morningstar"
  ),
  "firstnations.twospirit": entry(
    "firstnations.twospirit",
    "banner",
    "firstnations-twospirit",
    "twospirit"
  ),
  "firstnations.weave": entry("firstnations.weave", "banner", "firstnations-weave", "weave"),
  "firstnations.wheel": entry(
    "firstnations.wheel",
    "frame",
    "firstnations-wheel",
    "fourdirections"
  ),
  "firstnations.feather": entry(
    "firstnations.feather",
    "trophy",
    "firstnations-feather",
    "feather"
  ),
  "firstnations.handprint": entry(
    "firstnations.handprint",
    "trophy",
    "firstnations-handprint",
    "handprint"
  ),
  "firstnations.medicinewheel": entry(
    "firstnations.medicinewheel",
    "trophy",
    "firstnations-medicinewheel",
    "medicinewheel"
  ),
  "firstnations.twospiritfeathers": entry(
    "firstnations.twospiritfeathers",
    "trophy",
    "firstnations-twospirit",
    "twospirit"
  ),

  // One roundel per flag, for wherever anybody is from.
  "flag.argentina": entry("flag.argentina", "trophy", "flag-argentina", "flagargentina"),
  "flag.brazil": entry("flag.brazil", "trophy", "flag-brazil", "flagbrazil"),
  "flag.china": entry("flag.china", "trophy", "flag-china", "flagchina"),
  "flag.colombia": entry("flag.colombia", "trophy", "flag-colombia", "flagcolombia"),
  "flag.cuba": entry("flag.cuba", "trophy", "flag-cuba", "flagcuba"),
  "flag.egypt": entry("flag.egypt", "trophy", "flag-egypt", "flagegypt"),
  "flag.ethiopia": entry("flag.ethiopia", "trophy", "flag-ethiopia", "flagethiopia"),
  "flag.france": entry("flag.france", "trophy", "flag-france", "flagfrance"),
  "flag.ghana": entry("flag.ghana", "trophy", "flag-ghana", "flagghana"),
  "flag.greece": entry("flag.greece", "trophy", "flag-greece", "flaggreece"),
  "flag.haiti": entry("flag.haiti", "trophy", "flag-haiti", "flaghaiti"),
  "flag.india": entry("flag.india", "trophy", "flag-india", "flagindia"),
  "flag.indonesia": entry("flag.indonesia", "trophy", "flag-indonesia", "flagindonesia"),
  "flag.ireland": entry("flag.ireland", "trophy", "flag-ireland", "flagireland"),
  "flag.italy": entry("flag.italy", "trophy", "flag-italy", "flagitaly"),
  "flag.jamaica": entry("flag.jamaica", "trophy", "flag-jamaica", "flagjamaica"),
  "flag.japan": entry("flag.japan", "trophy", "flag-japan", "flagjapan"),
  "flag.kenya": entry("flag.kenya", "trophy", "flag-kenya", "flagkenya"),
  "flag.korea": entry("flag.korea", "trophy", "flag-korea", "flagkorea"),
  "flag.lebanon": entry("flag.lebanon", "trophy", "flag-lebanon", "flaglebanon"),
  "flag.mexico": entry("flag.mexico", "trophy", "flag-mexico", "flagmexico"),
  "flag.morocco": entry("flag.morocco", "trophy", "flag-morocco", "flagmorocco"),
  "flag.nigeria": entry("flag.nigeria", "trophy", "flag-nigeria", "flagnigeria"),
  "flag.pakistan": entry("flag.pakistan", "trophy", "flag-pakistan", "flagpakistan"),
  "flag.peru": entry("flag.peru", "trophy", "flag-peru", "flagperu"),
  "flag.philippines": entry("flag.philippines", "trophy", "flag-philippines", "flagphilippines"),
  "flag.poland": entry("flag.poland", "trophy", "flag-poland", "flagpoland"),
  "flag.samoa": entry("flag.samoa", "trophy", "flag-samoa", "flagsamoa"),
  "flag.southafrica": entry("flag.southafrica", "trophy", "flag-southafrica", "flagsouthafrica"),
  "flag.turkey": entry("flag.turkey", "trophy", "flag-turkey", "flagturkey"),
  "flag.ukraine": entry("flag.ukraine", "trophy", "flag-ukraine", "flagukraine"),
  "flag.vietnam": entry("flag.vietnam", "trophy", "flag-vietnam", "flagvietnam"),

  // Guilds, raid nights, arcades, patch day, and the table.
  "gaming.arcade": entry("gaming.arcade", "banner", "gaming-arcade", "arcade"),
  "gaming.buttons": entry("gaming.buttons", "frame", "gaming-buttons", "buttons"),
  "gaming.controller": entry("gaming.controller", "trophy", "gaming-controller", "controller"),

  "gridiron.endzone": entry("gridiron.endzone", "banner", "gridiron-endzone", "endzone"),
  "gridiron.laces": entry("gridiron.laces", "frame", "gridiron-laces", "laces"),
  "gridiron.pigskin": entry("gridiron.pigskin", "trophy", "gridiron-pigskin", "pigskin"),

  "heritage.kente": entry("heritage.kente", "banner", "heritage-kente", "kente"),
  "heritage.northstar": entry("heritage.northstar", "banner", "heritage-northstar", "northstar"),
  "heritage.cowries": entry("heritage.cowries", "frame", "heritage-cowries", "cowries"),
  "heritage.panafrican": entry("heritage.panafrican", "frame", "heritage-panafrican", "panafrican"),
  "heritage.crown": entry("heritage.crown", "trophy", "heritage-crown", "crown"),
  "heritage.fist": entry("heritage.fist", "trophy", "heritage-fist", "fist"),
  "heritage.flag": entry("heritage.flag", "trophy", "heritage-panafrican", "panafricanflag"),

  "hockey.rink": entry("hockey.rink", "banner", "hockey-rink", "rink"),
  "hockey.faceoff": entry("hockey.faceoff", "frame", "hockey-faceoff", "faceoff"),
  "hockey.puck": entry("hockey.puck", "trophy", "hockey-puck", "puck"),

  "hoops.court": entry("hoops.court", "banner", "hoops-court", "court"),
  "hoops.seams": entry("hoops.seams", "frame", "hoops-seams", "seams"),
  "hoops.swish": entry("hoops.swish", "trophy", "hoops-swish", "swish"),

  // Bands, choirs, anyone who books a room and plugs in.
  "music.festival": entry("music.festival", "banner", "music-festival", "festival"),
  "music.sheet": entry("music.sheet", "banner", "music-sheet", "sheetmusic", "dark"),
  "music.soundcheck": entry("music.soundcheck", "banner", "music-soundcheck", "soundcheck"),
  "music.vinyl": entry("music.vinyl", "frame", "music-vinyl", "vinyl"),
  "music.cassette": entry("music.cassette", "trophy", "music-cassette", "cassette"),
  "music.drums": entry("music.drums", "trophy", "music-drums", "drums"),
  "music.guitar": entry("music.guitar", "trophy", "music-guitar", "guitar"),
  "music.keys": entry("music.keys", "trophy", "music-keys", "keys"),
  "music.mic": entry("music.mic", "trophy", "music-mic", "microphone"),
  "music.sax": entry("music.sax", "trophy", "music-sax", "saxophone"),
  "music.turntable": entry("music.turntable", "trophy", "music-turntable", "turntable"),
  "music.violin": entry("music.violin", "trophy", "music-violin", "violin"),

  "nature.beach": entry("nature.beach", "banner", "nature-beach", "beach"),
  "nature.desert": entry("nature.desert", "banner", "nature-desert", "desert"),
  "nature.lake": entry("nature.lake", "banner", "nature-lake", "lake"),
  "nature.nightsky": entry("nature.nightsky", "banner", "nature-nightsky", "nightsky"),
  "nature.pines": entry("nature.pines", "frame", "nature-pines", "pines"),
  "nature.ridge": entry("nature.ridge", "frame", "nature-ridge", "ridge"),
  "nature.campfire": entry("nature.campfire", "trophy", "nature-campfire", "campfire"),
  "nature.mountain": entry("nature.mountain", "trophy", "nature-mountain", "mountain"),
  "nature.tent": entry("nature.tent", "trophy", "nature-tent", "tent"),

  "pets.catnap": entry("pets.catnap", "banner", "pets-catnap", "catnap"),
  "pets.fetch": entry("pets.fetch", "banner", "pets-fetch", "fetch"),
  "pets.collar": entry("pets.collar", "frame", "pets-collar", "collar"),
  "pets.bunny": entry("pets.bunny", "trophy", "pets-bunny", "rabbit"),
  "pets.cat": entry("pets.cat", "trophy", "pets-cat", "cat"),
  "pets.dog": entry("pets.dog", "trophy", "pets-dog", "dog"),
  "pets.hamster": entry("pets.hamster", "trophy", "pets-hamster", "hamster"),
  "pets.horse": entry("pets.horse", "trophy", "pets-horse", "horse"),
  "pets.lizard": entry("pets.lizard", "trophy", "pets-lizard", "lizard"),
  "pets.paw": entry("pets.paw", "trophy", "pets-paw", "pawprint"),
  "pets.rat": entry("pets.rat", "trophy", "pets-rat", "rat"),
  "pets.snake": entry("pets.snake", "trophy", "pets-snake", "snake"),

  // Foragers, houseplant keepers, and anyone who stops a walk to look at a log.
  "plants.grove": entry("plants.grove", "banner", "plants-grove", "grove"),
  "plants.overgrown": entry("plants.overgrown", "banner", "plants-overgrown", "overgrown"),
  "plants.windowsill": entry("plants.windowsill", "banner", "plants-windowsill", "windowsill"),
  "plants.nest": entry("plants.nest", "frame", "plants-nest", "nest"),
  "plants.rosette": entry("plants.rosette", "frame", "plants-rosette", "rosette"),
  "plants.vines": entry("plants.vines", "frame", "plants-vines", "vines"),
  "plants.monstera": entry("plants.monstera", "trophy", "plants-monstera", "monstera"),
  "plants.morel": entry("plants.morel", "trophy", "plants-morel", "morel"),
  "plants.succulent": entry("plants.succulent", "trophy", "plants-succulent", "succulent"),

  "pride.aceflag": entry("pride.aceflag", "banner", "pride-ace", "ace"),
  "pride.biflag": entry("pride.biflag", "banner", "pride-bi", "bi"),
  "pride.gayflag": entry("pride.gayflag", "banner", "pride-gay", "gay"),
  "pride.lesbianflag": entry("pride.lesbianflag", "banner", "pride-lesbian", "lesbian"),
  "pride.nonbinaryflag": entry("pride.nonbinaryflag", "banner", "pride-nonbinary", "nonbinary"),
  "pride.parade": entry("pride.parade", "banner", "pride-parade", "parade"),
  "pride.polyflag": entry("pride.polyflag", "banner", "pride-poly", "poly"),
  "pride.transflag": entry("pride.transflag", "banner", "pride-trans", "trans"),
  "pride.acering": entry("pride.acering", "frame", "pride-ace", "ace"),
  "pride.biring": entry("pride.biring", "frame", "pride-bi", "bi"),
  "pride.gayring": entry("pride.gayring", "frame", "pride-gay", "gay"),
  "pride.lesbianring": entry("pride.lesbianring", "frame", "pride-lesbian", "lesbian"),
  "pride.nonbinaryring": entry("pride.nonbinaryring", "frame", "pride-nonbinary", "nonbinary"),
  "pride.polyring": entry("pride.polyring", "frame", "pride-poly", "poly"),
  "pride.spectrum": entry("pride.spectrum", "frame", "pride-spectrum", "spectrum"),
  "pride.transring": entry("pride.transring", "frame", "pride-trans", "trans"),
  "pride.aceheart": entry("pride.aceheart", "trophy", "pride-ace", "ace"),
  "pride.biheart": entry("pride.biheart", "trophy", "pride-bi", "bi"),
  "pride.gayheart": entry("pride.gayheart", "trophy", "pride-gay", "gay"),
  "pride.heart": entry("pride.heart", "trophy", "pride-heart", "prideheart"),
  "pride.lesbianheart": entry("pride.lesbianheart", "trophy", "pride-lesbian", "lesbian"),
  "pride.nonbinaryheart": entry("pride.nonbinaryheart", "trophy", "pride-nonbinary", "nonbinary"),
  "pride.polyheart": entry("pride.polyheart", "trophy", "pride-poly", "poly"),
  "pride.transheart": entry("pride.transheart", "trophy", "pride-trans", "trans"),

  // Labs, field stations, reading groups with a whiteboard.
  "science.lab": entry("science.lab", "banner", "science-lab", "labbench"),
  "science.observatory": entry(
    "science.observatory",
    "banner",
    "science-observatory",
    "observatory"
  ),
  "science.helix": entry("science.helix", "frame", "science-helix", "helix"),
  "science.orbital": entry("science.orbital", "frame", "science-orbital", "orbital"),
  "science.ammonite": entry("science.ammonite", "trophy", "science-ammonite", "ammonite"),
  "science.benzene": entry("science.benzene", "trophy", "science-benzene", "benzene"),
  "science.dividers": entry("science.dividers", "trophy", "science-dividers", "dividers"),
  "science.dna": entry("science.dna", "trophy", "science-dna", "dna"),
  "science.flask": entry("science.flask", "trophy", "science-flask", "flask"),
  "science.hammer": entry("science.hammer", "trophy", "science-hammer", "rockhammer"),
  "science.magnet": entry("science.magnet", "trophy", "science-magnet", "magnet"),
  "science.microscope": entry("science.microscope", "trophy", "science-microscope", "microscope"),

  "soccer.floodlights": entry("soccer.floodlights", "banner", "soccer-floodlights", "floodlights"),
  "soccer.panels": entry("soccer.panels", "frame", "soccer-panels", "panels"),
  "soccer.matchball": entry("soccer.matchball", "trophy", "soccer-matchball", "matchball"),

  // The group that keeps October in the calendar all year.
  "spooky.hollow": entry("spooky.hollow", "banner", "spooky-hollow", "hollow"),
  "spooky.skeletons": entry("spooky.skeletons", "banner", "spooky-skeletons", "skeletons"),
  "spooky.witching": entry("spooky.witching", "banner", "spooky-witching", "witchinghour"),
  "spooky.bones": entry("spooky.bones", "frame", "spooky-bones", "bones"),
  "spooky.ironwork": entry("spooky.ironwork", "frame", "spooky-ironwork", "ironwork"),
  "spooky.web": entry("spooky.web", "frame", "spooky-web", "cobweb"),
  "spooky.bat": entry("spooky.bat", "trophy", "spooky-bat", "bat"),
  "spooky.ghost": entry("spooky.ghost", "trophy", "spooky-ghost", "ghost"),
  "spooky.lantern": entry("spooky.lantern", "trophy", "spooky-lantern", "lantern"),

  "tea.caddies": entry("tea.caddies", "banner", "tea-caddies", "caddies"),
  "tea.garden": entry("tea.garden", "banner", "tea-garden", "teagarden"),
  "tea.service": entry("tea.service", "banner", "tea-service", "teaservice"),
  "tea.leaves": entry("tea.leaves", "frame", "tea-leaves", "tealeaves"),
  "tea.porcelain": entry("tea.porcelain", "frame", "tea-porcelain", "porcelain"),
  "tea.bag": entry("tea.bag", "trophy", "tea-bag", "teabag"),
  "tea.cup": entry("tea.cup", "trophy", "tea-cup", "teacup"),
  "tea.matcha": entry("tea.matcha", "trophy", "tea-matcha", "matcha"),
  "tea.pot": entry("tea.pot", "trophy", "tea-pot", "teapot"),

  "tennis.clay": entry("tennis.clay", "banner", "tennis-clay", "clay", "dark"),
  "tennis.strings": entry("tennis.strings", "frame", "tennis-strings", "strings"),
  "tennis.ace": entry("tennis.ace", "trophy", "tennis-ace", "tennisace"),

  "travel.landmarks": entry("travel.landmarks", "banner", "travel-landmarks", "landmarks"),
  "travel.trainride": entry("travel.trainride", "banner", "travel-train", "bytrain"),
  "travel.meridians": entry("travel.meridians", "frame", "travel-meridians", "meridians"),
  "travel.bicycle": entry("travel.bicycle", "trophy", "travel-bicycle", "bicycle"),
  "travel.car": entry("travel.car", "trophy", "travel-car", "car"),
  "travel.globe": entry("travel.globe", "trophy", "travel-globe", "globe"),
  "travel.plane": entry("travel.plane", "trophy", "travel-plane", "plane"),
  "travel.ship": entry("travel.ship", "trophy", "travel-ship", "ship"),
  "travel.train": entry("travel.train", "trophy", "travel-train", "train"),

  "ttrpg.dicetower": entry("ttrpg.dicetower", "banner", "ttrpg-dicetower", "dicetower"),
  "ttrpg.natural20": entry("ttrpg.natural20", "frame", "ttrpg-natural20", "natural20"),
  "ttrpg.d20": entry("ttrpg.d20", "trophy", "ttrpg-d20", "d20"),

  "volleyball.beach": entry("volleyball.beach", "banner", "volleyball-beach", "beach"),
  "volleyball.net": entry("volleyball.net", "frame", "volleyball-net", "net"),
  "volleyball.spike": entry("volleyball.spike", "trophy", "volleyball-spike", "spike"),

  "winter.hearth": entry("winter.hearth", "banner", "winter-hearth", "hearth"),
  "winter.snowfall": entry("winter.snowfall", "banner", "winter-snowfall", "snowfall"),
  "winter.icicles": entry("winter.icicles", "frame", "winter-icicles", "icicles"),
  "winter.wreath": entry("winter.wreath", "frame", "winter-wreath", "wreath"),
  "winter.bauble": entry("winter.bauble", "trophy", "winter-bauble", "bauble"),
  "winter.cocoa": entry("winter.cocoa", "trophy", "winter-cocoa", "cocoa"),
  "winter.snowflake": entry("winter.snowflake", "trophy", "winter-snowflake", "snowflake"),
  "winter.snowman": entry("winter.snowman", "trophy", "winter-snowman", "snowman"),

  "world.street": entry("world.street", "banner", "world-street", "streetparty"),
  "world.bunting": entry("world.bunting", "frame", "world-bunting", "bunting"),

  "zen.garden": entry("zen.garden", "banner", "zen-garden", "garden"),
  "zen.sand": entry("zen.sand", "banner", "zen-sand", "rakedsand"),
  "zen.enso": entry("zen.enso", "frame", "zen-enso", "enso"),
  "zen.rake": entry("zen.rake", "frame", "zen-rake", "rakelines"),
  "zen.bell": entry("zen.bell", "trophy", "zen-bell", "singingbowl"),
  "zen.cairn": entry("zen.cairn", "trophy", "zen-cairn", "stones"),
  "zen.incense": entry("zen.incense", "trophy", "zen-incense", "incense"),
  "zen.koi": entry("zen.koi", "trophy", "zen-koi", "koi"),
  "zen.lotus": entry("zen.lotus", "trophy", "zen-lotus", "lotus"),
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

/** The trophies a profile is wearing that this build can draw, in the order worn. */
export const resolveTrophies = (
  decorations: ProfileDecorationsOutput | null | undefined
): Decoration[] =>
  (decorations?.trophies ?? [])
    .map((id) => resolveDecoration(id, "trophy"))
    .filter((trophy): trophy is Decoration => Boolean(trophy));
