/**
 * Device keys, as something a person can actually compare.
 *
 * Two screens have to be checked against each other by somebody holding both,
 * and a line of base64 is the worst possible thing to ask them to do it with:
 * it is long, it is case-sensitive, and every one of them looks like every
 * other one, so what actually happens is that nobody reads past the first few
 * characters. A handful of pictures is read in one glance and a wrong one is
 * obvious, which is the property that matters.
 *
 * Two forms, both iterated SHA-512 in the manner of Signal's fingerprint, so
 * finding a second key set with the same code costs thousands of hashes a try:
 *
 * - a **device code**, ten pictures for one device, for confirming a device of
 *   your own and for a new device somebody else added;
 * - a **safety number**, thirty digits per account over every device it lists,
 *   shown as two halves, for comparing a whole conversation with somebody.
 *
 * The list is the 64 emoji Matrix uses for the same job — chosen to be
 * recognisable at a glance, easy to name out loud, and hard to mistake for each
 * other. Names travel with them because the same code point is drawn
 * differently on different platforms, and "dog" is what two people compare over
 * a phone call.
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

/** How many pictures a device code is: sixty bits, six to a picture. */
export const DEVICE_CODE_LENGTH = 10;

/** How many rounds of SHA-512 a code is stretched over, as Signal's fingerprint. */
const ROUNDS = 5200;

const DEVICE_CODE_TAG = "initiative-dm-device-code-v1";
const SAFETY_NUMBER_TAG = "initiative-dm-safety-v1";

/** A device's two public keys, as the directory lists them. */
export interface CodeKeys {
  fingerprintKey: string;
  identityKey: string;
}

const bytesOf = (base64: string): Uint8Array =>
  Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));

const concat = (...parts: Uint8Array[]): Uint8Array<ArrayBuffer> => {
  const out = new Uint8Array(parts.reduce((total, part) => total + part.length, 0));
  let at = 0;
  for (const part of parts) {
    out.set(part, at);
    at += part.length;
  }
  return out;
};

/** A user id as eight bytes, most significant first, as the signed bytes carry it. */
const userIdBytes = (userId: number): Uint8Array => {
  const out = new Uint8Array(8);
  new DataView(out.buffer).setBigUint64(0, BigInt(userId));
  return out;
};

/** `seed`, then each round the previous digest followed by `key`. */
async function stretch(seed: Uint8Array, key: Uint8Array): Promise<Uint8Array> {
  let digest = seed;
  for (let round = 0; round < ROUNDS; round += 1) {
    digest = new Uint8Array(await crypto.subtle.digest("SHA-512", concat(digest, key)));
  }
  return digest;
}

/**
 * The pictures for one device of one account.
 *
 * Six bits at a time off the front of the digest, most significant first, the
 * same walk Matrix takes.
 */
export async function deviceCode(userId: number, keys: CodeKeys): Promise<SafetyEmoji[]> {
  const fingerprint = bytesOf(keys.fingerprintKey);
  const digest = await stretch(
    concat(
      new TextEncoder().encode(DEVICE_CODE_TAG),
      userIdBytes(userId),
      fingerprint,
      bytesOf(keys.identityKey)
    ),
    fingerprint
  );
  const code: SafetyEmoji[] = [];
  for (let index = 0; index < DEVICE_CODE_LENGTH; index += 1) {
    let value = 0;
    for (let bit = index * 6; bit < index * 6 + 6; bit += 1) {
      value = (value << 1) | ((digest[bit >> 3] >> (7 - (bit % 8))) & 1);
    }
    code.push(ALPHABET[value] as SafetyEmoji);
  }
  return code;
}

/**
 * One account's half of a safety number: thirty digits over every device it
 * lists, in six groups of five.
 *
 * The devices are sorted by their keys first, so the order the directory
 * happens to list them in does not change the number.
 */
export async function accountSafetyNumber(userId: number, devices: CodeKeys[]): Promise<string> {
  const listed = devices
    .map((device) => concat(bytesOf(device.fingerprintKey), bytesOf(device.identityKey)))
    .sort((left, right) => {
      for (let index = 0; index < Math.min(left.length, right.length); index += 1) {
        if (left[index] !== right[index]) return left[index] - right[index];
      }
      return left.length - right.length;
    });
  const keys = concat(...listed);
  const digest = await stretch(
    concat(new TextEncoder().encode(SAFETY_NUMBER_TAG), userIdBytes(userId), keys),
    keys
  );
  let digits = "";
  for (let group = 0; group < 6; group += 1) {
    let value = 0;
    for (const byte of digest.subarray(group * 5, group * 5 + 5)) value = value * 256 + byte;
    digits += String(value % 100000).padStart(5, "0");
  }
  return digits;
}
