/**
 * What can be named inside a comment or a document, and how it is written down.
 *
 * One trigger opens the picker over everything: `@` for people, `#` for
 * anything else. The type words after `#` — `#task:`, `#queue:` — narrow it,
 * and they are DERIVED from the generated entity types rather than listed, so
 * a tool added server-side can be mentioned the same day.
 *
 * The stored form is `#task[Label](12)`, which is shaped like a link on
 * purpose: markdown parses it before any text pass sees it, so a mention
 * written inside a code fence stays literal.
 */

import { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";

/** People. A separate trigger because they are read from the roster, not the
 *  index — identity is shared across communities, content is not. */
export const USER_TRIGGER = "@";

/** Everything else. */
export const ENTITY_TRIGGER = "#";

/**
 * What a `#` can reach: everything indexed except what people SAID about it.
 * A comment is not a thing you name — it is a remark on one, and the thing it
 * is on is what a reader wants.
 */
export const MENTIONABLE_TYPES: SearchEntityType[] = Object.values(SearchEntityType).filter(
  (type) => type !== SearchEntityType.comment
);

/** The word after `#` that narrows to one type: the type's own name, kebabed. */
export const typeTrigger = (type: SearchEntityType): string => type.replaceAll("_", "-");

/**
 * Trigger word -> type. Longest first, so `#counter-group` is not read as
 * `#counter` with a stray suffix.
 */
const TRIGGER_TYPES: [string, SearchEntityType][] = [
  ...MENTIONABLE_TYPES.map((type): [string, SearchEntityType] => [typeTrigger(type), type]),
  // Written by every composer before the type words were derived, and still
  // sitting in stored comments, so it is read as well as the derived spelling.
  ["doc", SearchEntityType.document] as [string, SearchEntityType],
].sort((a, b) => b[0].length - a[0].length);

/** The type a trigger word names, or `undefined` if it names none. */
export const typeForTrigger = (word: string): SearchEntityType | undefined =>
  TRIGGER_TYPES.find(([trigger]) => trigger === word)?.[1];

/** Every trigger word, longest first — what a parser matches against. */
export const TRIGGER_WORDS: string[] = TRIGGER_TYPES.map(([trigger]) => trigger);

/** How a chosen suggestion is written into a comment. */
export const entityMentionSyntax = (type: SearchEntityType, label: string, id: number): string =>
  `${ENTITY_TRIGGER}${typeTrigger(type)}[${label}](${id})`;

/** How a chosen person is written into a comment. */
export const userMentionSyntax = (label: string, id: number): string =>
  `${USER_TRIGGER}[${label}](${id})`;

/** What the composer is being asked for right now. */
export type MentionQuery = {
  /** `null` while typing after a bare `#` — every type is offered. */
  types: SearchEntityType[] | null;
  /** What has been typed after the trigger. */
  query: string;
  /** How many characters of the field the mention occupies, so replacing it
   *  removes the trigger too. */
  length: number;
};

/** A mention being typed: people, or things. */
export type ActiveMention = MentionQuery & { user: boolean };

//: `@word`, or `#word`, or `#type:word` — anchored to the end of what has been
//: typed, and only at a word boundary so an email address is not a mention.
const USER_PATTERN = /(^|[\s([{])@([^\s@#]*)$/;
const ENTITY_PATTERN = /(^|[\s([{])#([\w-]*)(?::([^\s#]*))?$/;

/**
 * The mention being typed at the end of `text`, or `null`.
 *
 * `#ven` is ambiguous — it could be a type word half-typed, or a search for
 * "ven" across everything — so it is treated as both: the search runs over
 * every type, and typing `:` is what commits to narrowing.
 */
export const activeMention = (text: string): ActiveMention | null => {
  const user = USER_PATTERN.exec(text);
  if (user) {
    return { user: true, types: null, query: user[2], length: user[2].length + 1 };
  }
  const entity = ENTITY_PATTERN.exec(text);
  if (!entity) return null;
  const [, , word, narrowed] = entity;
  if (narrowed === undefined) {
    return { user: false, types: null, query: word, length: word.length + 1 };
  }
  const type = typeForTrigger(word);
  if (!type) return null;
  return {
    user: false,
    types: [type],
    query: narrowed,
    length: word.length + narrowed.length + 2,
  };
};
