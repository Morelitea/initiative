/**
 * Verifying a new device of this account's against one it already trusts.
 *
 * Both devices make a fresh key pair for this comparison alone and swap the
 * public halves through the server; each derives the same four pictures from
 * the shared secret, and the person holding both says whether they match. The
 * device that answers commits to its key before it sees the other's, so each
 * comparison is a single try at pictures nobody could choose, and a new one
 * starts from new keys. Once the person says they match, each side vouches for
 * its own long-lived keys under the same secret, and the other checks that
 * against what the directory lists for it. A device is released only when both
 * have happened. Every message is signed with the sending device's own key, and
 * read only if it verifies against the directory's entry for that device.
 *
 * The device that holds the new one starts (`startVerification`); the other
 * answers whatever arrives in its relay inbox (`collectVerification`). One
 * comparison at a time per browser: the tab running one holds a lock, so
 * another tab of the same device does not read its messages.
 */

import {
  collectVerificationApiV1MeDmVerificationGet as collectInbox,
  sendVerificationApiV1MeDmVerificationPost as sendRelay,
} from "@/api/generated/direct-messages/direct-messages";

import { ratchet } from "./client";
import { type Context, ensureDeviceContext } from "./device";
import { answerNewDevice } from "./historySync";
import { emojiAt, type SafetyEmoji } from "./safetyCode";
import { accountPickle, type PeerKeyChange, peerKeyChanges } from "./store";
import type { TrustedDevice } from "./trust";

/** How long a comparison may take, as the server keeps its messages. */
const VERIFICATION_TTL_MS = 10 * 60 * 1000;

const LOCK = "initiative-dm-verification";
const EMOJI_INFO = "INITIATIVE_DEVICE_VERIFICATION_V1_EMOJI";
const MAC_INFO = "INITIATIVE_DEVICE_VERIFICATION_V1_MAC";

type FailReason = "mismatch" | "cancelled" | "timeout" | "elsewhere";

/** What the dialog draws. */
export type VerificationView =
  | { phase: "idle" }
  | { phase: "waiting"; device: TrustedDevice }
  | { phase: "compare"; device: TrustedDevice; emoji: SafetyEmoji[]; confirmed: boolean }
  | { phase: "verified"; device: TrustedDevice }
  | { phase: "failed"; device: TrustedDevice; reason: FailReason };

type Message =
  | { v: 1; txn: string; type: "start" }
  | { v: 1; txn: string; type: "accept"; commitment: string }
  | { v: 1; txn: string; type: "key"; key: string }
  | { v: 1; txn: string; type: "mac"; mac: string }
  | { v: 1; txn: string; type: "cancel"; reason: FailReason };

interface Attempt {
  txn: string;
  initiator: boolean;
  ctx: Context;
  peer: TrustedDevice;
  /** The `start` exactly as it travelled, which the commitment covers. */
  start: string;
  ourKey?: string;
  commitment?: string;
  established: boolean;
  confirmed: boolean;
  theirMac?: string;
  /** For the device that started: what the person answered about its history. */
  change?: PeerKeyChange;
  sendHistory: boolean;
  timer: ReturnType<typeof setTimeout>;
  release: () => void;
}

let attempt: Attempt | null = null;
let view: VerificationView = { phase: "idle" };
const listeners = new Set<() => void>();

function show(next: VerificationView): void {
  view = next;
  for (const listener of listeners) listener();
}

export function subscribeVerification(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function verificationView(): VerificationView {
  return view;
}

/**
 * Hold the verification lock until the returned function is called, or `null`
 * where another tab of this browser holds it. Browsers without Web Locks run
 * without one.
 */
function takeLock(): Promise<(() => void) | null> {
  const locks = typeof navigator === "undefined" ? undefined : navigator.locks;
  if (!locks) return Promise.resolve(() => undefined);
  return new Promise((resolve) => {
    locks
      .request(LOCK, { ifAvailable: true }, (lock) => {
        if (lock === null) return resolve(null);
        return new Promise<void>((release) => resolve(release));
      })
      .catch(() => resolve(null));
  });
}

const base64 = (bytes: ArrayBuffer) => btoa(String.fromCharCode(...new Uint8Array(bytes)));

async function commitmentTo(key: string, start: string): Promise<string> {
  return base64(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(key + start)));
}

/** A device's own two public keys, the text each side vouches for. */
const keysOf = (device: { fingerprintKey: string; identityKey: string }) =>
  `${device.fingerprintKey}|${device.identityKey}`;

function emojiInfo(current: Attempt, theirKey: string): string {
  const [initiator, responder] = current.initiator
    ? [
        [current.ctx.device, current.ourKey],
        [current.peer.id, theirKey],
      ]
    : [
        [current.peer.id, theirKey],
        [current.ctx.device, current.ourKey],
      ];
  return [EMOJI_INFO, current.ctx.self, ...initiator, ...responder, current.txn].join("|");
}

const macInfo = (current: Attempt, from: string, to: string) =>
  [MAC_INFO, current.ctx.self, from, to, current.txn].join("|");

/** What a device signs to say a relayed message is its own, and for whom. */
const signedText = (from: string, to: string, message: string) => `${from}|${to}|${message}`;

/**
 * Relay one message to the other device, signed with this device's own key so
 * the other side can tell it came from here.
 */
async function send(current: Pick<Attempt, "ctx" | "peer">, message: Message): Promise<string> {
  const text = JSON.stringify(message);
  const pickle = await accountPickle.get();
  if (!pickle) throw new Error("this device has no key store");
  const signature = await ratchet.signVerification(
    pickle,
    signedText(current.ctx.device, current.peer.id, text)
  );
  await sendRelay({
    device_id: current.ctx.device,
    to_device_id: current.peer.id,
    body: JSON.stringify({ message: text, signature }),
  });
  return text;
}

/** A relayed message, if its sender signed it for this device. */
async function opened(ctx: Context, sender: TrustedDevice, body: string): Promise<string | null> {
  try {
    const { message, signature } = JSON.parse(body) as { message?: unknown; signature?: unknown };
    if (typeof message !== "string" || typeof signature !== "string") return null;
    const signed = await ratchet.verifyVerification(
      sender.fingerprintKey,
      signedText(sender.id, ctx.device, message),
      signature
    );
    return signed ? message : null;
  } catch {
    return null;
  }
}

/** Whether `current` is still the comparison this tab is running. */
const live = (current: Attempt) => attempt === current;

/** Stop `current`, leaving `next` on screen. Nothing, if it has already ended. */
function finish(current: Attempt, next: VerificationView): void {
  if (!live(current)) return;
  clearTimeout(current.timer);
  current.release();
  void ratchet.verificationClose(current.txn).catch(() => undefined);
  attempt = null;
  show(next);
}

async function fail(current: Attempt, reason: FailReason, tell = true): Promise<void> {
  if (!live(current)) return;
  finish(current, { phase: "failed", device: current.peer, reason });
  if (tell) {
    await send(current, { v: 1, txn: current.txn, type: "cancel", reason }).catch(() => undefined);
  }
}

function begin(fields: Omit<Attempt, "timer" | "established" | "confirmed">): Attempt {
  const current: Attempt = {
    ...fields,
    established: false,
    confirmed: false,
    timer: setTimeout(() => void fail(current, "timeout"), VERIFICATION_TTL_MS),
  };
  attempt = current;
  show({ phase: "waiting", device: current.peer });
  return current;
}

/**
 * Start comparing with a new device of this account's, from the prompt about it.
 * `sendHistory` is what the prompt says to do about its history once verified.
 */
export async function startVerification(
  change: PeerKeyChange,
  { sendHistory }: { sendHistory: boolean }
): Promise<void> {
  if (attempt) return;
  const ctx = await ensureDeviceContext();
  const peer = [...ctx.own.held, ...ctx.own.devices].find(
    (device) => device.id === change.deviceId
  );
  if (!peer) throw new Error("that device is not listed any more");
  const release = await takeLock();
  if (!release) {
    show({ phase: "failed", device: peer, reason: "elsewhere" });
    return;
  }
  const txn = crypto.randomUUID();
  const current = begin({
    txn,
    initiator: true,
    ctx,
    peer,
    start: "",
    change,
    sendHistory,
    release,
  });
  try {
    current.start = await send(current, { v: 1, txn, type: "start" });
  } catch (error) {
    finish(current, { phase: "idle" });
    throw error;
  }
}

/**
 * The person says the pictures match. This side vouches for its keys, and the
 * device is released once the other side's word has arrived as well.
 */
export async function confirmMatch(): Promise<void> {
  const current = attempt;
  if (!current?.established || view.phase !== "compare" || view.confirmed) return;
  show({ ...view, confirmed: true });
  try {
    const me = current.ctx.own.devices.find((device) => device.id === current.ctx.device);
    if (!me) return fail(current, "cancelled");
    const mac = await ratchet.verificationMac(
      current.txn,
      keysOf(me),
      macInfo(current, current.ctx.device, current.peer.id)
    );
    if (!live(current)) return;
    await send(current, { v: 1, txn: current.txn, type: "mac", mac });
  } catch (error) {
    await fail(current, "cancelled");
    throw error;
  }
  current.confirmed = true;
  await settle(current);
}

/** The person says the pictures do not match. */
export async function rejectMatch(): Promise<void> {
  if (attempt) await fail(attempt, "mismatch");
}

/** The dialog was closed before the comparison ended. */
export async function cancelVerification(): Promise<void> {
  if (attempt) await fail(attempt, "cancelled");
  show({ phase: "idle" });
}

/** Put an ended comparison away. */
export function dismissVerification(): void {
  if (!attempt) show({ phase: "idle" });
}

/** Both halves are in: this side said they match, and the other side vouched for its keys. */
async function settle(current: Attempt): Promise<void> {
  if (!current.confirmed || current.theirMac === undefined || !live(current)) return;
  const vouched = await ratchet.verificationCheckMac(
    current.txn,
    keysOf(current.peer),
    macInfo(current, current.peer.id, current.ctx.device),
    current.theirMac
  );
  if (!live(current)) return;
  if (!vouched) return fail(current, "mismatch");
  if (current.change) {
    await answerNewDevice(current.change, { mine: true, sendHistory: current.sendHistory });
  } else if (current.ctx.own.held.some((device) => device.id === current.peer.id)) {
    await peerKeyChanges.acknowledge([current.peer.id]);
  }
  finish(current, { phase: "verified", device: current.peer });
}

function parse(text: string): Message | null {
  try {
    const message = JSON.parse(text) as Partial<Message>;
    if (message.v !== 1 || typeof message.txn !== "string") return null;
    const field = (name: string) => typeof (message as Record<string, unknown>)[name] === "string";
    switch (message.type) {
      case "start":
        return message as Message;
      case "accept":
        return field("commitment") ? (message as Message) : null;
      case "key":
        return field("key") ? (message as Message) : null;
      case "mac":
        return field("mac") ? (message as Message) : null;
      case "cancel":
        return message as Message;
      default:
        return null;
    }
  } catch {
    return null;
  }
}

async function showCode(current: Attempt, theirKey: string): Promise<void> {
  await ratchet.verificationEstablish(current.txn, theirKey);
  current.established = true;
  const indices = await ratchet.verificationEmoji(current.txn, emojiInfo(current, theirKey));
  if (!live(current)) return;
  show({
    phase: "compare",
    device: current.peer,
    emoji: indices.map((index) => emojiAt(index)),
    confirmed: false,
  });
}

/** Answer a `start` from another of this account's devices. */
async function answer(ctx: Context, peer: TrustedDevice, start: string, txn: string) {
  if (attempt) {
    await send({ ctx, peer }, { v: 1, txn, type: "cancel", reason: "cancelled" }).catch(
      () => undefined
    );
    return;
  }
  const current = begin({
    txn,
    initiator: false,
    ctx,
    peer,
    start,
    sendHistory: false,
    release: () => undefined,
  });
  try {
    current.ourKey = await ratchet.verificationOpen(txn);
    const commitment = await commitmentTo(current.ourKey, start);
    if (!live(current)) return;
    await send(current, { v: 1, txn, type: "accept", commitment });
  } catch (error) {
    await fail(current, "cancelled");
    throw error;
  }
}

async function handle(current: Attempt, message: Message): Promise<void> {
  if (message.type === "cancel") {
    return fail(current, message.reason === "mismatch" ? "mismatch" : "cancelled", false);
  }
  if (current.initiator && message.type === "accept" && current.ourKey === undefined) {
    current.commitment = message.commitment;
    current.ourKey = await ratchet.verificationOpen(current.txn);
    if (!live(current)) return;
    await send(current, { v: 1, txn: current.txn, type: "key", key: current.ourKey });
    return;
  }
  if (current.initiator && message.type === "key" && current.commitment && !current.established) {
    if ((await commitmentTo(message.key, current.start)) !== current.commitment) {
      return fail(current, "mismatch");
    }
    return showCode(current, message.key);
  }
  if (!current.initiator && message.type === "key" && current.ourKey && !current.established) {
    await send(current, { v: 1, txn: current.txn, type: "key", key: current.ourKey });
    return showCode(current, message.key);
  }
  if (message.type === "mac" && current.established && current.theirMac === undefined) {
    current.theirMac = message.mac;
    return settle(current);
  }
  // Anything else is out of order, which a comparison does not recover from.
  return fail(current, "cancelled");
}

let collecting: Promise<void> = Promise.resolve();

/**
 * Read this device's relay inbox and act on it: answer a comparison another
 * device started, or carry on the one in progress. One read at a time in a tab,
 * so messages are handled in the order they were sent. A message its sender
 * did not sign for this device is passed over.
 */
export function collectVerification(): Promise<void> {
  const next = collecting.then(collectOnce);
  collecting = next.catch(() => undefined);
  return next;
}

async function collectOnce(): Promise<void> {
  let release: (() => void) | null = null;
  if (!attempt) {
    release = await takeLock();
    if (!release) return;
  }
  let handling: Attempt | null = null;
  try {
    const ctx = attempt?.ctx ?? (await ensureDeviceContext());
    const { items } = await collectInbox({ device_id: ctx.device });
    for (const item of items) {
      const sender = [...ctx.own.devices, ...ctx.own.held].find(
        (device) => device.id === item.sender_device_id
      );
      const text = sender ? await opened(ctx, sender, item.body) : null;
      const message = text === null ? null : parse(text);
      if (!sender || text === null || !message) continue;
      if (message.type === "start") {
        await answer(ctx, sender, text, message.txn);
        handling = attempt;
        if (attempt && release) {
          attempt.release = release;
          release = null;
        }
      } else if (attempt && message.txn === attempt.txn && sender.id === attempt.peer.id) {
        handling = attempt;
        await handle(attempt, message);
      }
    }
  } catch (error) {
    if (handling) await fail(handling, "cancelled");
    throw error;
  } finally {
    release?.();
  }
}
