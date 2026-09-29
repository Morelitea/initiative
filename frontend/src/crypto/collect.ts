/**
 * Collect everything waiting for this device, decrypt it, and act on it.
 *
 * Acknowledging deletes the row on the server, so the local log is written
 * first — losing a message to a failed write is worse than collecting it twice.
 */

import {
  acknowledgeQueueApiV1MeDmQueueAckPost as ackQueue,
  collectQueueApiV1MeDmQueueGet as collectQueue,
} from "@/api/generated/direct-messages/direct-messages";

import { type Context, ensureDeviceContext } from "./device";
import { type Batch, KINDS, type KindSpec, unpack } from "./envelope";
import { requestHistory, serveHistory } from "./historySync";
import { acknowledge } from "./send";
import { type Destination, readPreKey, readWithHeldSession } from "./sessions";
import { accountPickle, peerKeyChanges } from "./store";
import { runThreadCatchUps, serveThreadHistory } from "./threadHistory";

/** The members of one conversation other than this account, as the server lists them. */
async function rosterOf(ctx: Context, conversationId: string): Promise<number[]> {
  return (await ctx.conversations()).find((row) => row.id === conversationId)?.member_ids ?? [];
}

/**
 * The device a pre-key message in one conversation came from, by the identity
 * it names.
 *
 * The queue row carries no sender, so it is one of this account's own
 * confirmed devices -- its outbox arriving from another client -- or a device
 * of somebody on the conversation's roster. A device of this account's that is
 * waiting to be confirmed is noted as having something here, and its message
 * waits in the queue until it is.
 */
async function senderOf(
  ctx: Context,
  conversationId: string,
  identityKey: string,
  asking: Set<string>
): Promise<Destination | undefined> {
  const own = ctx.own.devices.find((device) => device.identityKey === identityKey);
  if (own) return { ...own, origin: "self" };
  const waiting = ctx.own.held.find((device) => device.identityKey === identityKey);
  if (waiting) {
    asking.add(waiting.id);
    return undefined;
  }
  for (const userId of await rosterOf(ctx, conversationId)) {
    const theirs = (await ctx.directory(userId)).devices.find(
      (device) => device.identityKey === identityKey
    );
    if (theirs) return { ...theirs, origin: "other" };
  }
  return undefined;
}

/**
 * Collect everything waiting for this device.
 *
 * One collection runs at a time across every tab of this browser: two at once
 * decrypt the same rows and race each other's ratchet steps. One asked for
 * while another runs waits for it and then runs too, because the row that
 * prompted it may have arrived after the running one read the queue. A third
 * finds that one already waiting, and has nothing to add. Browsers without Web
 * Locks (Safari before 15.4) collect as they are asked.
 */
export function collect(options: { receipts?: boolean } = {}): Promise<string[]> {
  const locks = typeof navigator === "undefined" ? undefined : navigator.locks;
  if (!locks) return collectOnce(options);
  return new Promise<string[]>((resolve, reject) => {
    locks
      .request("initiative-dm-collect-waiting", { ifAvailable: true }, (waiting) => {
        if (waiting === null) return resolve([]);
        // Held until this one starts running, then let go: a collection asked
        // for after that point may have something new to read.
        return new Promise<void>((started) => {
          locks
            .request("initiative-dm-collect", () => {
              started();
              return collectOnce(options).then(resolve, reject);
            })
            .catch((error: unknown) => {
              started();
              reject(error);
            });
        });
      })
      .catch(reject);
  });
}

async function collectOnce({ receipts = true }: { receipts?: boolean }): Promise<string[]> {
  const ctx = await ensureDeviceContext();
  // Before the queue is read: a device that has just arrived, or a conversation
  // somebody has just joined, has nothing waiting, and asking is the whole
  // reason it has nothing.
  await requestHistory(ctx).catch(() => undefined);
  await runThreadCatchUps(ctx).catch(() => undefined);

  const { items } = await collectQueue({ device_id: ctx.device });
  if (items.length > 0 && !(await accountPickle.get())) {
    throw new Error("this device has no key store");
  }

  const batch: Batch = { own: ctx.own.devices, landed: new Map(), asking: [] };
  const waiting = new Set<string>();
  const touched = new Set<string>();
  const collected: number[] = [];
  for (const item of items) {
    try {
      const read =
        item.message_type === 0
          ? await readPreKey(item, (identityKey) =>
              senderOf(ctx, item.conversation_id, identityKey, waiting)
            )
          : await readWithHeldSession(item, new Set(await rosterOf(ctx, item.conversation_id)));
      if (read === null) continue;
      // `null` is a kind from a later version: understood well enough to know it
      // is not for this one, and taken off the server rather than tried again.
      const envelope = unpack(read.plaintext, String(item.id));
      const kind: KindSpec<unknown> | null = envelope && KINDS[envelope.kind];
      if (
        envelope &&
        kind &&
        (kind.from === "any" || kind.from === (read.mine ? "self" : "other"))
      ) {
        const changed = await kind.handle(
          envelope,
          {
            conversationId: item.conversation_id,
            createdAt: item.created_at,
            mine: read.mine,
            author: read.author,
            device: read.device,
          },
          batch
        );
        if (changed) touched.add(changed);
      }
      collected.push(item.id);
    } catch {
      // A message this device cannot read is left on the server rather than
      // acknowledged away: it stays collectable if the reason is fixable.
    }
  }
  if (collected.length > 0) {
    await ackQueue({ device_id: ctx.device, message_ids: collected });
  }
  // What the prompt about a new device of this account's reads, so the
  // history it asked for is offered already ticked.
  await peerKeyChanges.markAsked([...waiting]);

  // After the acknowledgement, so a request that arrived in this batch is
  // served in it -- and on an empty queue too, for one approved since the
  // collection that noted it. Resumable, so a failure waits for the next.
  await serveHistory(ctx).catch(() => undefined);
  // One transfer per ask, so a second ask in the same batch is one answer.
  const answered = new Set<string>();
  for (const ask of batch.asking) {
    if (answered.has(ask.requestId)) continue;
    answered.add(ask.requestId);
    // A failure leaves their next ask to reach somebody else.
    await serveThreadHistory(ctx, ask.conversationId, ask.requestId, ask.userId).catch(
      () => undefined
    );
  }

  // After the acknowledgement, and never in its way: a receipt is a courtesy
  // and the queue row it is about is already safely on this device.
  if (receipts && batch.landed.size > 0) {
    const conversations = await ctx.conversations().catch(() => []);
    for (const conversation of conversations) {
      const ids = batch.landed.get(conversation.id);
      if (!ids) continue;
      await acknowledge(ctx, conversation.id, conversation.member_ids ?? [], ids, "delivered");
    }
  }
  return [...touched];
}
