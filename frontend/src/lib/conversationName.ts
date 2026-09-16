/**
 * What to call a conversation.
 *
 * A pair is called by the person on the other side. A group has no name and is
 * not going to get one — a title would be the first piece of conversation
 * content the server could read — so it is called by who is on it, which is
 * also how it is found again now that a roster is unique.
 */

/** Everybody on it except the reader, as the server named them. */
export const rosterNames = (conversation: {
  member_handles?: string[];
  member_ids?: number[];
}): string[] => (conversation.member_handles ?? []).filter((handle) => handle.length > 0);

/**
 * A group's name, from its roster.
 *
 * Every name, not the first few: one conversation is told from another by who
 * is on it, so dropping names is dropping the thing that tells them apart. A
 * long one wraps, which is the row's problem and not this function's.
 */
export const groupName = (conversation: { member_handles?: string[] }): string =>
  rosterNames(conversation).join(", ");

/** Whether this conversation has more than two people on it. */
export const isGroup = (conversation: { kind?: string }): boolean => conversation.kind === "group";
