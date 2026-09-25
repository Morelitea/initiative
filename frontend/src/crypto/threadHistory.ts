/**
 * Catching up on a group joined late: nothing was kept for somebody who was
 * still deciding, so they ask the members who were there, and one sends it.
 */

import type { Context } from "./device";
import { newMessageId, sendTransfer } from "./envelope";
import { sendEnvelope } from "./send";
import { type ReactionSides, type StoredMessage, threadCatchUp } from "./store";

/**
 * How long an unanswered ask waits before the next member on the roster is
 * asked instead: long enough that somebody who is there is not overtaken while
 * their transfer runs, short enough that the first name on a list does not
 * hold a thread up for the evening.
 */
const CATCH_UP_RETRY_MS = 60 * 1000;

/**
 * Ask to be sent what was said on this conversation before now.
 *
 * Recorded rather than sent: the ask goes out on the next collection, which is
 * also what retries it. Only a group ever wants this -- a pair does not exist
 * until both sides have agreed, so there is never anything said before you
 * were there.
 */
export async function wantThreadHistory(conversationId: string): Promise<void> {
  // An empty time reads as never asked, so the next collection asks at once.
  await threadCatchUp.set(conversationId, { requestId: newMessageId(), asked: 0, at: "" });
}

/**
 * Send the outstanding ask for each conversation waiting to be caught up.
 *
 * One member per round, in the order the roster comes in. Asking everybody at
 * once would land the whole thread on this device once per member, and the
 * copies would be identical. A member who cannot be written to counts as
 * asked: a client that cannot be reached is a client that cannot answer.
 *
 * The round ends when the roster is exhausted, so a conversation whose members
 * are all away is given up on rather than asked forever.
 */
export async function runThreadCatchUps(ctx: Context): Promise<void> {
  const open = await threadCatchUp.all();
  const wanted = Object.keys(open);
  if (wanted.length === 0) return;
  const conversations = await ctx.conversations();
  const now = Date.now();
  for (const conversationId of wanted) {
    const state = open[conversationId];
    const asked = Date.parse(state.at);
    if (!Number.isNaN(asked) && now - asked < CATCH_UP_RETRY_MS) continue;
    const conversation = conversations.find((row) => row.id === conversationId);
    const roster = conversation?.member_ids ?? [];
    if (state.asked >= roster.length) {
      // Everybody has been asked, or there is nobody left to ask.
      await threadCatchUp.clear(conversationId);
      continue;
    }
    try {
      await sendEnvelope(
        ctx,
        conversationId,
        [roster[state.asked]],
        { v: 1, kind: "thread-history-request", requestId: state.requestId },
        // Nothing here is news, and nothing about it is theirs to be told.
        { toSelf: false, silent: true }
      );
    } catch {
      // Unreachable is an answer of sorts: the next round asks somebody else.
    }
    await threadCatchUp.set(conversationId, {
      ...state,
      asked: state.asked + 1,
      at: new Date().toISOString(),
    });
  }
}

/**
 * Reactions as the person receiving them holds them.
 *
 * A log records which of two sides put each emoji there, so this account's own
 * are the other side's once they are somebody else's.
 */
const theirSideOf = (reactions: Record<string, ReactionSides>): Record<string, ReactionSides> =>
  Object.fromEntries(
    Object.entries(reactions).map(([emoji, sides]) => [
      emoji,
      { mine: false, theirs: sides.mine || sides.theirs },
    ])
  );

/**
 * One entry of this device's log, as the person being sent it will read it.
 *
 * A log is written from its holder's own side, so handing one over unchanged
 * would file this account's words as the recipient's own. Its receipts go with
 * it: they are this account's record of where its own copies got to, and mean
 * nothing on somebody else's.
 *
 * This account's own messages carry no author -- a log does not name the
 * person keeping it -- and none is added here. The far end knows who sent the
 * transfer, which is a better answer than this device asking who it is.
 */
const asSeenByThem = (entry: StoredMessage): StoredMessage => {
  const carried: StoredMessage = { ...entry };
  if (entry.reactions) carried.reactions = theirSideOf(entry.reactions);
  if (!entry.mine) return carried;
  carried.receipt = undefined;
  carried.author = undefined;
  carried.mine = false;
  return carried;
};

/**
 * Send a member what was said on this conversation before they answered.
 *
 * Nobody approves this. The asker is on the conversation -- the server will
 * not carry anything into it otherwise -- and a group's roster is fixed, so
 * every message being sent was written to a roster they were already on.
 *
 * A transfer that stops part way is left there: what got through is already
 * waiting for them, and their next ask reaches somebody else.
 */
export async function serveThreadHistory(
  ctx: Context,
  conversationId: string,
  requestId: string,
  toUserId: number
): Promise<void> {
  await sendTransfer([conversationId], 0, ({ messages, seq, last }) =>
    sendEnvelope(
      ctx,
      conversationId,
      [toUserId],
      { v: 1, kind: "thread-history", requestId, seq, last, messages: messages.map(asSeenByThem) },
      { toSelf: false, silent: true }
    )
  );
}
