/**
 * History between this account's own devices: a new device asks its elders
 * once, and each sends every thread it holds if the person said so when they
 * confirmed the new device there.
 */

import { removeDeviceApiV1MeDmDevicesDeviceIdDelete as removeDevice } from "@/api/generated/direct-messages/direct-messages";

import type { Context } from "./device";
import { type Envelope, newMessageId, sendTransfer } from "./envelope";
import { deliver } from "./send";
import {
  approvedDevices,
  type HistoryProgress,
  historyAsk,
  historyProgress,
  messageLog,
  type PeerKeyChange,
  peerKeyChanges,
  pendingHistoryRequest,
} from "./store";
import type { TrustedDevice } from "./trust";

/**
 * Hand one envelope to one device of this account's own.
 *
 * It rides inside a conversation, because that is the only channel the server
 * offers, but the conversation is a carrier and nothing more: the envelope
 * names the conversation it is *about*, so history for one somebody can no
 * longer be written to still reaches the device that asked for it.
 */
function sendToOwnDevice(
  ctx: Context,
  carrierId: string,
  device: TrustedDevice,
  envelope: Envelope,
  wake = false
): Promise<boolean> {
  return deliver(ctx, carrierId, [{ ...device, origin: "self" }], [], envelope, {
    silent: true,
    wake,
  });
}

/** A conversation any own-device traffic can travel inside. */
const carrierConversation = async (ctx: Context) => (await ctx.conversations())[0]?.id ?? null;

/**
 * Which of two devices came first.
 *
 * A strict total order, and the same one on both sides: each device works out
 * for itself which way an ask should travel, and they have to agree without
 * conferring. Registration time decides it; the id breaks a tie, so two devices
 * registered in the same instant still order one before the other rather than
 * each deciding it is the junior one.
 */
const precedes = (a: TrustedDevice, b: TrustedDevice): boolean => {
  const at = Date.parse(a.createdAt ?? "");
  const bt = Date.parse(b.createdAt ?? "");
  if (!Number.isNaN(at) && !Number.isNaN(bt) && at !== bt) return at < bt;
  return a.id < b.id;
};

/**
 * Ask this account's other devices for the history this one cannot derive.
 *
 * Asked once per device: the answer is a person's decision, and a device that
 * asks on every start trains somebody to say yes without reading. Only a device
 * that arrived empty asks — recorded at registration, and read back here — and
 * it asks only devices that came before it: history runs forwards, and when
 * both ends think they are eligible this is what settles the direction. A
 * device with nobody before it is the account's origin, so its question is
 * closed here. Only devices this one has confirmed are asked, and only those
 * it asked can answer.
 *
 * Eligibility survives a failed attempt: a message collected between two
 * attempts says nothing about whether the older ones are here.
 */
export async function requestHistory(ctx: Context): Promise<boolean> {
  const state = await historyAsk.get();
  if (state !== undefined && state !== "eligible") return false;
  if (state === undefined) {
    // A device registered before registration started recording the answer.
    // Its log is the only evidence left of which kind of device it is.
    if (await messageLog.holdsAnything()) {
      await historyAsk.close();
      return false;
    }
    await historyAsk.eligible();
  }
  const me = ctx.own.devices.find((device) => device.id === ctx.device);
  if (!me) return false;
  const elders = ctx.own.devices.filter(
    (device) => device.id !== ctx.device && precedes(device, me)
  );
  if (elders.length === 0) {
    // Nobody to ask, now or later: this device is the oldest the account has,
    // and nothing registered after it can hold what it is missing. Closed
    // rather than merely skipped, because an eligibility left standing is one
    // that fires at whichever device happens to arrive next.
    await historyAsk.close();
    return false;
  }
  const carrier = await carrierConversation(ctx);
  if (carrier === null) return false;

  const requestId = newMessageId();
  const asked: string[] = [];
  for (const device of elders) {
    const sent = await sendToOwnDevice(
      ctx,
      carrier,
      device,
      {
        v: 1,
        kind: "history-request",
        requestId,
        deviceId: ctx.device,
        fingerprint: me.fingerprintKey,
      },
      // The one ask that has to reach a device nobody is looking at.
      true
    );
    if (sent) asked.push(device.id);
  }
  // Written down once it is on its way rather than once it is answered: the
  // queue holds it until the far device wakes, and a device that asks on every
  // collection raises the same prompt until somebody stops reading it. The id
  // and the devices it went to are what an answer is matched against.
  if (asked.length > 0) await historyAsk.open(requestId, asked);
  return asked.length > 0;
}

/**
 * How long the notice about an unanswered ask is worth keeping on screen.
 *
 * A day: long enough to cover going to fetch the other device, or leaving it
 * until the evening, and short enough that a laptop nobody ever went and
 * confirmed is not still being told about it a week later.
 */
export const HISTORY_ASK_NOTICE_MS = 24 * 60 * 60 * 1000;

/** The moment the notice about an unanswered ask stops. */
export interface HistoryAskWaiting {
  /** Epoch milliseconds. */
  expiresAt: number;
}

/**
 * Whether this device is waiting for another of this account's to confirm it
 * and send its history.
 *
 * The notice gives up after a day; the question does not. Nothing expires a
 * queued request, so a device opened next week still delivers it and its
 * answer still lands here — the ask stays open and the transfer arrives
 * whether or not there was anything on screen about it. What stops after a
 * day is telling somebody to go and do a thing they have had a day to do.
 */
export async function historyAskWaiting(): Promise<HistoryAskWaiting | undefined> {
  const ask = await historyAsk.get();
  if (typeof ask !== "object" || !ask.at) return undefined;
  // Put away by hand. The day is an outside limit on a notice nobody dealt
  // with, not the only way to be rid of one.
  if (ask.dismissed) return undefined;
  const asked = Date.parse(ask.at);
  if (Number.isNaN(asked)) return undefined;
  const expiresAt = asked + HISTORY_ASK_NOTICE_MS;
  if (expiresAt <= Date.now()) return undefined;
  // When it stops, so the screen showing it can take it down on its own rather
  // than at whatever unrelated moment something next happens to ask again.
  return { expiresAt };
}

/**
 * Answer the prompt about a new device of this account's.
 *
 * Yes lets it be addressed and read from, and, with `sendHistory`, approves it
 * for this device's history, which is sent once it asks. No withdraws it from
 * the account; the prompt clears once the server has done so.
 */
export async function answerNewDevice(
  change: PeerKeyChange,
  { mine, sendHistory }: { mine: boolean; sendHistory: boolean }
): Promise<void> {
  if (!mine) {
    await removeDevice(change.deviceId);
  } else {
    await approvedDevices.decide(change.deviceId, change.now.fingerprint, sendHistory);
  }
  await peerKeyChanges.acknowledge([change.deviceId]);
}

/**
 * Answer a history request from a confirmed device of this account's: send it
 * this device's history where the person approved that, and a no where they
 * did not, so the far device stops waiting.
 *
 * Resumable from this side, which is the side that stops: a tab closed
 * mid-transfer picks up at the conversation it had reached, and what was
 * already sent is waiting in the queue for the far device whether or not this
 * one comes back.
 */
export async function serveHistory(ctx: Context): Promise<void> {
  const pending = await pendingHistoryRequest.get();
  if (!pending) return;

  // Waiting on the person's answer about this device.
  if (ctx.own.held.some((entry) => entry.id === pending.deviceId)) return;
  const device = ctx.own.devices.find((entry) => entry.id === pending.deviceId);
  const carrier = await carrierConversation(ctx);
  if (!device || carrier === null || device.fingerprintKey !== pending.fingerprint) {
    // The device it came from is gone, or is not the one it was confirmed
    // as. Neither is a thing to keep trying.
    await pendingHistoryRequest.clear();
    return;
  }
  const decision = await approvedDevices.decision(pending.deviceId, pending.fingerprint);
  if (decision === undefined) {
    // A device this browser already trusted, which nobody has been asked about
    // yet: the same question a new device gets, with its request waiting.
    await peerKeyChanges.raise({
      userId: ctx.self,
      deviceId: device.id,
      now: { fingerprint: device.fingerprintKey, identityKey: device.identityKey },
      at: new Date().toISOString(),
      label: device.label,
      asked: true,
    });
    return;
  }
  if (!decision) {
    await sendToOwnDevice(ctx, carrier, device, {
      v: 1,
      kind: "history-declined",
      requestId: pending.requestId,
    });
    await pendingHistoryRequest.clear();
    return;
  }

  const held = await historyProgress.get(device.id);
  const progress: HistoryProgress =
    held?.requestId === pending.requestId
      ? held
      : { requestId: pending.requestId, done: [], seq: 0 };
  // What this device holds, not what the server still lists: a conversation
  // somebody left is off that list and its messages are still here.
  const remaining = (await messageLog.conversations()).filter(
    (conversationId) => !progress.done.includes(conversationId)
  );

  const finished = await sendTransfer(
    remaining,
    progress.seq,
    async ({ conversationId, messages, seq, last }) => {
      const sent = await sendToOwnDevice(ctx, carrier, device, {
        v: 1,
        kind: "history",
        requestId: pending.requestId,
        seq,
        last,
        conversationId,
        messages,
      });
      if (sent) {
        progress.seq = seq;
        await historyProgress.set(device.id, progress);
      }
      return sent;
    },
    async (conversationId) => {
      progress.done.push(conversationId);
      await historyProgress.set(device.id, progress);
    }
  );
  // Kept until the far device has been told it has the lot, so a transfer
  // that stopped short of that is carried on by the next collection.
  if (finished) await pendingHistoryRequest.clear();
}
