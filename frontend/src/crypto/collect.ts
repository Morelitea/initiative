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
import { type Destination, openInboundSession, readWithHeldSession } from "./sessions";
import { accountPickle } from "./store";
import { runThreadCatchUps, serveThreadHistory } from "./threadHistory";

/**
 * The identity keys a pre-key message in each conversation could have come from.
 *
 * The queue row carries no sender, so it is one of the conversation's members
 * or one of this account's own clients -- a pre-key message anywhere may be its
 * own outbox arriving from another client. Only conversations that actually
 * have one are looked up.
 */
async function identitiesForPreKeys(
  ctx: Context,
  conversationIds: Set<string>
): Promise<Map<string, Destination[]>> {
  const candidates = new Map<string, Destination[]>();
  if (conversationIds.size === 0) return candidates;
  const ours: Destination[] = ctx.ownDevices.map((device) => ({
    id: device.id,
    identityKey: device.identity_key,
    origin: "self",
  }));
  const conversations = await ctx.conversations();
  for (const conversationId of conversationIds) {
    const roster = conversations.find((row) => row.id === conversationId)?.member_ids ?? [];
    const theirs = await Promise.all(
      roster.map(async (userId) =>
        (await ctx.directory(userId)).devices.map(
          (device): Destination => ({
            id: device.device_id,
            identityKey: device.identity_key,
            origin: "other",
            userId,
          })
        )
      )
    );
    candidates.set(conversationId, [...theirs.flat(), ...ours]);
  }
  return candidates;
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
  // Reading a directory claims nothing, so it costs no prekey.
  const candidates = await identitiesForPreKeys(
    ctx,
    new Set(items.filter((item) => item.message_type === 0).map((item) => item.conversation_id))
  );

  const batch: Batch = { ownDevices: ctx.ownDevices, landed: new Map(), asking: [] };
  const touched = new Set<string>();
  const collected: number[] = [];
  for (const item of items) {
    try {
      // Every message is offered to the sessions this device already holds
      // before any new one is opened -- pre-key messages included. A session
      // goes on marking what it sends as pre-key until it hears back on it, so
      // the second and third of those name a prekey the receiver has already
      // spent: opening a session is the one thing that cannot answer them, and
      // the session that can is sitting right here.
      const read =
        (await readWithHeldSession(item)) ??
        (item.message_type === 0
          ? await openInboundSession(item, candidates.get(item.conversation_id) ?? [])
          : null);
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
