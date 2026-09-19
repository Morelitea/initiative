/**
 * What to call a conversation, and who to draw on it.
 *
 * A pair is called by the person on the other side. A group has no name and is
 * not going to get one — a title would be the first piece of conversation
 * content the server could read — so it is called by who is on it, which is
 * also how it is found again now that a roster is unique.
 *
 * The roster arrives with the conversation rather than being looked up. A
 * roster needs no accepted request between every pair on it, so a client can be
 * in a conversation with somebody it has no other way to name.
 */

import type { DmRosterMember } from "@/api/generated/initiativeAPI.schemas";
import { getUserHandle } from "@/lib/userDisplay";

/** Everybody on it except the reader, as the server sent them. */
export const roster = (conversation: { members?: DmRosterMember[] }): DmRosterMember[] =>
  conversation.members ?? [];

/** Everybody on it except the reader, as handles. */
export const rosterNames = (conversation: { members?: DmRosterMember[] }): string[] =>
  roster(conversation)
    .map((member) => getUserHandle(member))
    .filter((handle) => handle.length > 0);

/**
 * A group's name, from its roster.
 *
 * Every name, not the first few: one conversation is told from another by who
 * is on it, so dropping names is dropping the thing that tells them apart. A
 * long one wraps, which is the row's problem and not this function's.
 */
export const groupName = (conversation: { members?: DmRosterMember[] }): string =>
  rosterNames(conversation).join(", ");

/** Whether this conversation has more than two people on it. */
export const isGroup = (conversation: { kind?: string }): boolean => conversation.kind === "group";
