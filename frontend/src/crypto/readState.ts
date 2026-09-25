/**
 * What this device has read of each thread.
 *
 * Counted by position in the log rather than by time: the log is in the order
 * this device learned of each message. A marker whose message is not in the
 * log leaves everything unread, which is the side to be wrong on. Only the
 * other side counts: your own message is not news to you.
 */

import { acknowledge } from "./send";
import { lastRead, messageLog, type StoredMessage } from "./store";

/** Their messages after the last one this device looked at. */
async function unread(conversationId: string): Promise<StoredMessage[]> {
  const [log, seen] = await Promise.all([
    messageLog.get(conversationId),
    lastRead.get(conversationId),
  ]);
  const read = seen ? log.findIndex((message) => message.id === seen) : -1;
  return log.slice(read + 1).filter((message) => !message.mine);
}

/** How much of one thread arrived after this device last looked at it. */
export async function unreadIn(conversationId: string): Promise<number> {
  return (await unread(conversationId)).length;
}

/**
 * This thread has been looked at, up to the last message the other side sent.
 *
 * Answers how many messages this look actually read, which is zero for the
 * common case of a thread that was already current. The caller uses it to
 * decide whether there is anything to report.
 */
export async function markRead(
  conversationId: string,
  { memberIds, receipts = true }: { memberIds?: number[]; receipts?: boolean } = {}
): Promise<number> {
  // Only what this look actually read. Reporting the whole thread every time
  // the marker is touched would say "read" again on every keystroke that
  // lengthened it, for messages answered an hour ago.
  const newly = await unread(conversationId);
  if (newly.length === 0) return 0;

  await lastRead.set(conversationId, newly[newly.length - 1].id);
  if (receipts && memberIds !== undefined) {
    await acknowledge(
      undefined,
      conversationId,
      memberIds,
      newly.map((message) => message.id),
      "read"
    );
  }
  return newly.length;
}
