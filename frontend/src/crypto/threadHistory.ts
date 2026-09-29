/**
 * Catching up on a group joined late: nothing was kept for somebody who was
 * still deciding, so they ask the members who were there, and each sends what
 * they said.
 */

import type { Context } from "./device";
import { newMessageId, sendTransfer } from "./envelope";
import { sendEnvelope } from "./send";
import { type StoredMessage, threadCatchUp } from "./store";

/**
 * How long an ask waits for members who have not finished answering. A member
 * who is away answers when they next open the app, so it is a day rather than
 * a minute; the rest of the thread arrives meanwhile from those who are there.
 */
const CATCH_UP_WAIT_MS = 24 * 60 * 60 * 1000;

/**
 * Ask to be sent what was said on this conversation before now.
 *
 * Recorded rather than sent: the ask goes out on the next collection, which is
 * also what retries it. Only a group ever wants this -- a pair does not exist
 * until both sides have agreed, so there is never anything said before you
 * were there.
 */
export async function wantThreadHistory(conversationId: string): Promise<void> {
  await threadCatchUp.set(conversationId, { requestId: newMessageId(), at: "" });
}

/**
 * Send the outstanding ask for each conversation waiting to be caught up.
 *
 * Every member at once: each sends only their own messages, so the answers do
 * not overlap. The ask closes member by member as each sends its last part,
 * and for whoever is left once the wait is up.
 */
export async function runThreadCatchUps(ctx: Context): Promise<void> {
  const open = await threadCatchUp.all();
  const wanted = Object.keys(open);
  if (wanted.length === 0) return;
  const conversations = await ctx.conversations();
  const now = Date.now();
  for (const conversationId of wanted) {
    const state = open[conversationId];
    if (Array.isArray(state.waiting)) {
      if (now - Date.parse(state.at) >= CATCH_UP_WAIT_MS) await threadCatchUp.clear(conversationId);
      continue;
    }
    const roster = conversations.find((row) => row.id === conversationId)?.member_ids ?? [];
    if (roster.length === 0) {
      await threadCatchUp.clear(conversationId);
      continue;
    }
    try {
      await sendEnvelope(
        ctx,
        conversationId,
        roster,
        { v: 1, kind: "thread-history-request", requestId: state.requestId },
        // Nothing here is news, and nothing about it is theirs to be told.
        { toSelf: false, silent: true }
      );
    } catch {
      // Nobody reachable yet: the next collection asks again.
      continue;
    }
    await threadCatchUp.set(conversationId, {
      ...state,
      waiting: roster,
      at: new Date().toISOString(),
    });
  }
}

/**
 * One of this account's own messages, as the member being sent it will file it.
 *
 * Theirs to read and never theirs to have said: it arrives as the other side,
 * with none of this account's receipts or the reactions on it, and no author,
 * which the far end takes from the session it arrives on.
 */
const asSeenByThem = ({
  receipt: _receipt,
  reactions: _reactions,
  author: _author,
  ...entry
}: StoredMessage): StoredMessage => ({ ...entry, mine: false });

/**
 * Send a member what this account said on this conversation before they
 * answered. Only this account's own messages: everybody else sends theirs.
 *
 * Nobody approves this. The asker is on the conversation -- the server will
 * not carry anything into it otherwise -- and a group's roster is fixed, so
 * every message being sent was written to a roster they were already on.
 *
 * A transfer that stops part way is left there: what got through is already
 * waiting for them.
 */
export async function serveThreadHistory(
  ctx: Context,
  conversationId: string,
  requestId: string,
  toUserId: number
): Promise<void> {
  await sendTransfer([conversationId], 0, async ({ messages, seq, last }) => {
    const said = messages.filter((entry) => entry.mine).map(asSeenByThem);
    // A part holding none of this account's messages has nothing to carry.
    if (said.length === 0 && !last) return true;
    return sendEnvelope(
      ctx,
      conversationId,
      [toUserId],
      { v: 1, kind: "thread-history", requestId, seq, last, messages: said },
      { toSelf: false, silent: true }
    );
  });
}
