/**
 * The pictures a verification between two of an account's devices shows.
 *
 * A handful of pictures is read in one glance and a wrong one is obvious,
 * which is the property that matters when two screens have to be checked
 * against each other by somebody holding both. Which pictures come from the
 * comparison itself (`./verification`): each one is new, so the pictures are
 * different every time.
 *
 * The list is the 64 emoji Matrix uses for the same job — chosen to be
 * recognisable at a glance, easy to name out loud, and hard to mistake for each
 * other — in Matrix's order, which is the order the ratchet's indices count in.
 * Names travel with them because the same code point is drawn differently on
 * different platforms.
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

/** One picture of a verification, by its index in the list. */
export function emojiAt(index: number): SafetyEmoji {
  const entry = ALPHABET[index];
  if (!entry) throw new Error("no such picture");
  return entry;
}
