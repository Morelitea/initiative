/**
 * A device key, as something a person can actually compare.
 *
 * Two screens have to be checked against each other by somebody holding both,
 * and a line of base64 is the worst possible thing to ask them to do it with:
 * it is long, it is case-sensitive, and every one of them looks like every
 * other one, so what actually happens is that nobody reads past the first few
 * characters. A handful of pictures is read in one glance and a wrong one is
 * obvious, which is the property that matters.
 *
 * The list is the 64 emoji Matrix uses for the same job — chosen to be
 * recognisable at a glance, easy to name out loud, and hard to mistake for each
 * other. Names travel with them because the same code point is drawn
 * differently on different platforms, and "dog" is what two people compare over
 * a phone call.
 *
 * This renders a public key rather than agreeing a shared secret, so it says
 * "this is the device you are looking at", not "nobody is in the middle". That
 * is the same thing the key it replaces said.
 */

/** Index order is the wire format: never reorder, only ever append at 64. */
const ALPHABET = [
  { emoji: "🐶", name: "dog" },
  { emoji: "🐱", name: "cat" },
  { emoji: "🦁", name: "lion" },
  { emoji: "🐎", name: "horse" },
  { emoji: "🦄", name: "unicorn" },
  { emoji: "🐷", name: "pig" },
  { emoji: "🐘", name: "elephant" },
  { emoji: "🐰", name: "rabbit" },
  { emoji: "🐼", name: "panda" },
  { emoji: "🐓", name: "rooster" },
  { emoji: "🐧", name: "penguin" },
  { emoji: "🐢", name: "turtle" },
  { emoji: "🐟", name: "fish" },
  { emoji: "🐙", name: "octopus" },
  { emoji: "🦋", name: "butterfly" },
  { emoji: "🌷", name: "flower" },
  { emoji: "🌳", name: "tree" },
  { emoji: "🌵", name: "cactus" },
  { emoji: "🍄", name: "mushroom" },
  { emoji: "🌏", name: "globe" },
  { emoji: "🌙", name: "moon" },
  { emoji: "☁️", name: "cloud" },
  { emoji: "🔥", name: "fire" },
  { emoji: "🍌", name: "banana" },
  { emoji: "🍎", name: "apple" },
  { emoji: "🍓", name: "strawberry" },
  { emoji: "🌽", name: "corn" },
  { emoji: "🍕", name: "pizza" },
  { emoji: "🎂", name: "cake" },
  { emoji: "❤️", name: "heart" },
  { emoji: "🙂", name: "smiley" },
  { emoji: "🤖", name: "robot" },
  { emoji: "🎩", name: "hat" },
  { emoji: "👓", name: "glasses" },
  { emoji: "🔧", name: "spanner" },
  { emoji: "🎅", name: "santa" },
  { emoji: "👍", name: "thumbsUp" },
  { emoji: "☂️", name: "umbrella" },
  { emoji: "⌛", name: "hourglass" },
  { emoji: "⏰", name: "clock" },
  { emoji: "🎁", name: "gift" },
  { emoji: "💡", name: "lightBulb" },
  { emoji: "📕", name: "book" },
  { emoji: "✏️", name: "pencil" },
  { emoji: "📎", name: "paperclip" },
  { emoji: "✂️", name: "scissors" },
  { emoji: "🔒", name: "lock" },
  { emoji: "🔑", name: "key" },
  { emoji: "🔨", name: "hammer" },
  { emoji: "☎️", name: "telephone" },
  { emoji: "🏁", name: "flag" },
  { emoji: "🚂", name: "train" },
  { emoji: "🚲", name: "bicycle" },
  { emoji: "✈️", name: "aeroplane" },
  { emoji: "🚀", name: "rocket" },
  { emoji: "🏆", name: "trophy" },
  { emoji: "⚽", name: "ball" },
  { emoji: "🎸", name: "guitar" },
  { emoji: "🎺", name: "trumpet" },
  { emoji: "🔔", name: "bell" },
  { emoji: "⚓", name: "anchor" },
  { emoji: "🎧", name: "headphones" },
  { emoji: "📁", name: "folder" },
  { emoji: "📌", name: "pin" },
] as const;

/**
 * The name of one picture, which is also its key under `safetyEmoji`.
 *
 * Narrow rather than `string` so a picture without a translation is a build
 * failure instead of a label reading `safetyEmoji.newthing` on the one screen
 * nobody can afford to be unsure about.
 */
export type SafetyEmojiName = (typeof ALPHABET)[number]["name"];

/** One picture, and the name to show under it. */
export interface SafetyEmoji {
  emoji: string;
  name: SafetyEmojiName;
}

/** How many pictures a code is. Six of sixty-four is 68 billion codes. */
export const SAFETY_CODE_LENGTH = 6;

/**
 * The key's bytes, however it happens to be written.
 *
 * Base64 is what the directory holds. Anything else is read as its own
 * characters rather than refused: the picture only has to be the same on both
 * screens, and a code that cannot be drawn is a comparison nobody can make.
 */
function bytesOf(fingerprint: string): number[] {
  try {
    const decoded = atob(fingerprint);
    return [...decoded].map((character) => character.charCodeAt(0) & 0xff);
  } catch {
    return [...new TextEncoder().encode(fingerprint)];
  }
}

/**
 * The pictures for one device key.
 *
 * Six bits at a time, most significant first, which is the same walk Matrix
 * takes: the first pictures come from the front of the key, so two codes that
 * differ anywhere near the start differ visibly. A key too short to fill the
 * code — never a real one — wraps rather than running out.
 */
export function safetyCode(fingerprint: string, length = SAFETY_CODE_LENGTH): SafetyEmoji[] {
  const bytes = bytesOf(fingerprint);
  if (bytes.length === 0) return [];
  const code: SafetyEmoji[] = [];
  for (let index = 0; index < length; index += 1) {
    const start = index * 6;
    let value = 0;
    for (let bit = 0; bit < 6; bit += 1) {
      const position = start + bit;
      const byte = bytes[Math.floor(position / 8) % bytes.length] ?? 0;
      value = (value << 1) | ((byte >> (7 - (position % 8))) & 1);
    }
    code.push(ALPHABET[value] as SafetyEmoji);
  }
  return code;
}
