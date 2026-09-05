/**
 * What the client does around the ratchet.
 *
 * The ratchet itself is proved in `ratchet.test.ts` against the real
 * implementation. What is on trial here is the orchestration: which side of a
 * thread a collected message lands on, when a prekey is spent, and what happens
 * when there is nobody to deliver to. None of that is visible to the type
 * checker — a message attributed to the wrong person still compiles.
 */

import "fake-indexeddb/auto";

import { beforeEach, describe, expect, it, vi } from "vitest";

/** Prekeys the stand-in account has already spent. Cleared per test. */
const spent = vi.hoisted(() => new Set<string>());

const api = vi.hoisted(() => ({
  listDevices: vi.fn(),
  readDirectory: vi.fn(),
  claimSessionKeys: vi.fn(),
  claimOwnSessionKeys: vi.fn(),
  sendMessages: vi.fn(),
  collectQueue: vi.fn(),
  ackQueue: vi.fn(),
  listConversations: vi.fn(),
  registerDevice: vi.fn(),
  removeDevice: vi.fn(),
  topUpKeys: vi.fn(),
}));

vi.mock("@/api/generated/direct-messages/direct-messages", () => ({
  listDevicesApiV1MeDmDevicesGet: () => api.listDevices(),
  readDirectoryApiV1UsersUserIdDmDevicesGet: (userId: number) => api.readDirectory(userId),
  claimSessionKeysApiV1UsersUserIdDmSessionKeysPost: (userId: number) =>
    api.claimSessionKeys(userId),
  claimOwnSessionKeysApiV1MeDmSessionKeysPost: (body: unknown) => api.claimOwnSessionKeys(body),
  sendMessagesApiV1MeDmConversationsConversationIdMessagesPost: (id: string, body: unknown) =>
    api.sendMessages(id, body),
  collectQueueApiV1MeDmQueueGet: (params: unknown) => api.collectQueue(params),
  acknowledgeQueueApiV1MeDmQueueAckPost: (body: unknown) => api.ackQueue(body),
  listConversationsApiV1MeDmConversationsGet: () => api.listConversations(),
  registerDeviceApiV1MeDmDevicesPost: (body: unknown) => api.registerDevice(body),
  removeDeviceApiV1MeDmDevicesDeviceIdDelete: (id: string) => api.removeDevice(id),
  topUpKeysApiV1MeDmOneTimeKeysPost: (body: unknown) => api.topUpKeys(body),
}));

/**
 * A stand-in ratchet whose ciphertext names its sender.
 *
 * The real one refuses an identity key that did not write the message, which is
 * exactly the behaviour the collection loop leans on when it tries each device
 * in turn. This reproduces that rule and nothing else.
 */
vi.mock("./client", () => ({
  ratchet: {
    createAccount: async () => ({ pickle: "account", identity_key: "mine", fingerprint_key: "fp" }),
    generateKeys: async (pickle: string, count: number, withFallback: boolean) => ({
      pickle: `${pickle}+${count}`,
      one_time_keys: Array.from({ length: count }, (_, index) => ({
        key_id: `k${index}`,
        public_key: `pk${index}`,
      })),
      fallback_key: withFallback ? { key_id: "fb", public_key: "fbpk" } : null,
    }),
    createOutboundSession: async (_pickle: string, identity: string) => ({
      session_pickle: `session:${identity}`,
      session_id: `session:${identity}`,
    }),
    createInboundSession: async (pickle: string, identity: string, ciphertext: string) => {
      const message = JSON.parse(ciphertext);
      if (message.from !== identity) throw new Error("not this device");
      // A prekey opens exactly one session: the real account forgets the one it
      // just spent, so the same pre-key message cannot open a second.
      if (message.prekey) {
        if (spent.has(message.prekey)) throw new Error("that prekey is spent");
        spent.add(message.prekey);
      }
      return {
        account_pickle: `${pickle}-spent`,
        session_pickle: `session:${identity}`,
        session_id: `session:${identity}`,
        plaintext: message.body,
      };
    },
    // Both ends of a ratchet move on with every message. The "!" is that step,
    // so a lost one is visible in the stored pickle.
    encrypt: async (sessionPickle: string, plaintext: string) => ({
      session_pickle: `${sessionPickle}!`,
      message_type: 1,
      ciphertext: JSON.stringify({ from: "mine", body: plaintext }),
    }),
    decrypt: async (sessionPickle: string, _type: number, ciphertext: string) => {
      const message = JSON.parse(ciphertext);
      if (!sessionPickle.startsWith(`session:${message.from}`)) {
        throw new Error("not this session");
      }
      return { session_pickle: `${sessionPickle}!`, plaintext: message.body };
    },
  },
}));

import {
  collect,
  ensureDevice,
  forgetMessagesOnThisDevice,
  markRead,
  RecipientHasNoDeviceError,
  sendText,
  unreadIn,
} from "./messaging";
import {
  accountPickle,
  deviceClaim,
  deviceId,
  forgetDevice,
  messageLog,
  sessionPickle,
} from "./store";

const OURS = { id: "device-1", identity_key: "mine" };
const OUR_PHONE = { id: "device-2", identity_key: "phone" };
const THEIRS = { device_id: "device-9", identity_key: "theirs", fingerprint_key: "fp" };

const ownDevice = (device: { id: string; identity_key: string }, keysHeld = 50) => ({
  ...device,
  fingerprint_key: "fp",
  label: null,
  created_at: "2026-09-01T00:00:00Z",
  last_seen_at: "2026-09-01T00:00:00Z",
  one_time_key_count: keysHeld,
});

const queued = (overrides: Record<string, unknown>) => ({
  id: 1,
  conversation_id: "conv-1",
  message_type: 0,
  created_at: "2026-09-01T00:00:00Z",
  ...overrides,
});

const from = (identity: string, body: string, prekey?: string) =>
  JSON.stringify({ from: identity, body, prekey });

beforeEach(async () => {
  await forgetDevice();
  spent.clear();
  vi.clearAllMocks();
  // A device that is already registered: the registration path has its own
  // tests, and every case here starts after it.
  await deviceId.set(OURS.id);
  await accountPickle.set("account");
  api.listDevices.mockResolvedValue({ devices: [ownDevice(OURS), ownDevice(OUR_PHONE)] });
  api.readDirectory.mockResolvedValue({ user_id: 7, devices: [THEIRS] });
  api.claimSessionKeys.mockResolvedValue({
    user_id: 7,
    devices: [{ ...THEIRS, one_time_key: { key_id: "k", public_key: "pk" } }],
  });
  api.claimOwnSessionKeys.mockResolvedValue({
    user_id: 1,
    devices: [
      {
        device_id: OUR_PHONE.id,
        identity_key: OUR_PHONE.identity_key,
        fingerprint_key: "fp",
        one_time_key: { key_id: "k", public_key: "pk" },
      },
    ],
  });
  api.listConversations.mockResolvedValue({
    conversations: [{ id: "conv-1", other_user_id: 7, created_at: "2026-09-01T00:00:00Z" }],
  });
  api.collectQueue.mockResolvedValue({ items: [] });
  api.sendMessages.mockResolvedValue(undefined);
  api.ackQueue.mockResolvedValue(undefined);
  api.topUpKeys.mockResolvedValue({ devices: [] });
});

describe("collecting", () => {
  it("puts a message from the other party on their side of the thread", async () => {
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from("theirs", "how are you") })],
    });

    await collect();

    expect(await messageLog.get("conv-1")).toEqual([
      expect.objectContaining({ body: "how are you", mine: false }),
    ]);
  });

  it("puts a message from this account's own device on this side", async () => {
    // The outbox arriving from another client of the same account. It carries
    // no sender, and attributing it to the other party would show somebody
    // their own words as if they had been written to them.
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from("phone", "sent from the phone") })],
    });

    await collect();

    expect(await messageLog.get("conv-1")).toEqual([
      expect.objectContaining({ body: "sent from the phone", mine: true }),
    ]);
  });

  it("keeps an ordinary message on the side its session belongs to", async () => {
    // Only the first message of a session names an identity. Everything after
    // it is read on the session, so which side it belongs to has to have been
    // written down when the session was opened.
    api.collectQueue.mockResolvedValue({
      items: [
        queued({ id: 1, payload: from("phone", "first") }),
        queued({ id: 2, message_type: 1, payload: from("phone", "second") }),
      ],
    });

    await collect();

    expect(await messageLog.get("conv-1")).toEqual([
      expect.objectContaining({ body: "first", mine: true }),
      expect.objectContaining({ body: "second", mine: true }),
    ]);
  });

  it("reads a directory only for conversations a pre-key message arrived in", async () => {
    api.collectQueue.mockResolvedValue({
      items: [queued({ message_type: 1, payload: from("theirs", "ordinary") })],
    });

    await collect();

    expect(api.readDirectory).not.toHaveBeenCalled();
  });

  it("reads an ordinary message on a session opened in another conversation", async () => {
    // One device is in every conversation this account has — its own other
    // clients are — so the session it opened in one carries messages in the
    // next. A message that finds no session is never readable again.
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from("phone", "opened here") })],
    });
    await collect();

    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          id: 2,
          conversation_id: "conv-2",
          message_type: 1,
          payload: from("phone", "carried on"),
        }),
      ],
    });
    await collect();

    expect(await messageLog.get("conv-2")).toEqual([
      expect.objectContaining({ body: "carried on", mine: true }),
    ]);
  });

  it("reads a repeated pre-key message on the session it already opened", async () => {
    // A sender goes on marking its messages as pre-key until it hears back on
    // that session, so the second and third of them name a prekey the receiver
    // has already spent. Opening a session is the one thing that cannot answer
    // them, and reaching for it first is how a conversation used to die after
    // exactly one message each way.
    api.collectQueue.mockResolvedValue({
      items: [
        queued({ id: 1, payload: from(THEIRS.identity_key, "first", "otk-1") }),
        queued({ id: 2, payload: from(THEIRS.identity_key, "second", "otk-1") }),
      ],
    });

    await collect();

    expect(await messageLog.get("conv-1")).toEqual([
      expect.objectContaining({ body: "first", mine: false }),
      expect.objectContaining({ body: "second", mine: false }),
    ]);
    expect(api.ackQueue).toHaveBeenCalledWith({ device_id: OURS.id, message_ids: [1, 2] });
  });

  it("answers on the session a pre-key message opened rather than a second one", async () => {
    // The reply looks a session up by the device it is with, and until the
    // inbound path recorded that, answering somebody this device was already
    // talking to opened a fresh session and spent another of their prekeys.
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from(THEIRS.identity_key, "hello", "otk-1") })],
    });
    await collect();
    api.collectQueue.mockResolvedValue({ items: [] });

    await sendText("conv-1", 7, "hello back");

    expect(api.claimSessionKeys).not.toHaveBeenCalled();
  });

  it("tells the sender their message reached this device", async () => {
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from(THEIRS.identity_key, "hello", "otk-1") })],
    });

    await collect();

    // One receipt naming what arrived, addressed to their devices and not to
    // this account's own -- a receipt for yourself tells nobody anything.
    const [, body] = api.sendMessages.mock.calls[0];
    // And it announces nothing: the far end is woken to collect it, but a bell
    // line naming a sender and counting what they said is not what this is.
    expect(body.silent).toBe(true);
    expect(
      body.messages.map((message: { recipient_device_id: string }) => message.recipient_device_id)
    ).toEqual([THEIRS.device_id]);
    const [stored] = await messageLog.get("conv-1");
    expect(JSON.parse(JSON.parse(body.messages[0].payload).body)).toEqual({
      v: 1,
      kind: "receipt",
      state: "delivered",
      ids: [stored.id],
    });
  });

  it("says nothing about a message when receipts are switched off", async () => {
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from(THEIRS.identity_key, "hello", "otk-1") })],
    });

    await collect({ receipts: false });

    expect(api.sendMessages).not.toHaveBeenCalled();
    // The message is still collected and read: the switch is about what this
    // account reports, not about what it receives.
    expect(await messageLog.get("conv-1")).toHaveLength(1);
  });

  it("moves a message forward when a receipt for it arrives", async () => {
    const sent = await sendText("conv-1", 7, "hello");
    api.sendMessages.mockClear();
    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          message_type: 1,
          payload: from(
            THEIRS.identity_key,
            JSON.stringify({ v: 1, kind: "receipt", state: "read", ids: [sent.id] })
          ),
        }),
      ],
    });

    await collect();

    const [stored] = await messageLog.get("conv-1");
    expect(stored.receipt).toBe("read");
    // A receipt is news, not a message: it does not join the thread.
    expect(await messageLog.get("conv-1")).toHaveLength(1);
  });

  it("does not let a receipt fall back to an earlier state", async () => {
    // A device that was away collects a read and a delivered together, in
    // whichever order the queue holds them.
    const sent = await sendText("conv-1", 7, "hello");
    const receipt = (state: string) =>
      from(THEIRS.identity_key, JSON.stringify({ v: 1, kind: "receipt", state, ids: [sent.id] }));
    api.collectQueue.mockResolvedValue({
      items: [
        queued({ id: 1, message_type: 1, payload: receipt("read") }),
        queued({ id: 2, message_type: 1, payload: receipt("delivered") }),
      ],
    });

    await collect();

    expect((await messageLog.get("conv-1"))[0].receipt).toBe("read");
  });

  it("reports only what this look actually read", async () => {
    // markRead runs on every change to the thread's length. Reporting the whole
    // thread each time would say "read" again for messages answered an hour ago
    // -- once per keystroke that lengthened it.
    api.collectQueue.mockResolvedValue({
      items: [
        queued({ id: 1, payload: from(THEIRS.identity_key, "first", "otk-1") }),
        queued({ id: 2, payload: from(THEIRS.identity_key, "second", "otk-1") }),
      ],
    });
    await collect({ receipts: false });
    const log = await messageLog.get("conv-1");

    await markRead("conv-1", { otherUserId: 7 });
    const first = JSON.parse(
      JSON.parse(api.sendMessages.mock.calls[0][1].messages[0].payload).body
    );
    expect(first).toEqual({
      v: 1,
      kind: "receipt",
      state: "read",
      ids: [log[0].id, log[1].id],
    });

    api.sendMessages.mockClear();
    await markRead("conv-1", { otherUserId: 7 });
    expect(api.sendMessages).not.toHaveBeenCalled();
  });

  it("reads a half-written envelope as the words it may always have been", async () => {
    // An envelope missing the id it promised would be filed under `undefined`,
    // where the next one like it looks like the same message and is dropped as
    // a duplicate -- acknowledged away, off the server, never in the log.
    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          id: 1,
          payload: from(THEIRS.identity_key, JSON.stringify({ v: 1, kind: "text" }), "otk-1"),
        }),
        queued({
          id: 2,
          payload: from(THEIRS.identity_key, JSON.stringify({ v: 1, kind: "text" })),
        }),
      ],
    });

    await collect({ receipts: false });

    // Two messages, two entries: the queue row's id is unique per item.
    expect(await messageLog.get("conv-1")).toHaveLength(2);
  });

  it("ignores a receipt that does not say what it is about", async () => {
    const sent = await sendText("conv-1", 7, "hello");
    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          message_type: 1,
          payload: from(
            THEIRS.identity_key,
            JSON.stringify({ v: 1, kind: "receipt", state: "read" })
          ),
        }),
      ],
    });

    await collect({ receipts: false });

    // Not a receipt it can act on, so the message keeps the state it had.
    const stored = (await messageLog.get("conv-1")).find((m) => m.id === sent.id);
    expect(stored?.receipt).toBeUndefined();
  });

  it("leaves a message it cannot read on the server", async () => {
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from("a-device-nobody-knows", "unreadable") })],
    });

    await collect();

    expect(api.ackQueue).not.toHaveBeenCalled();
    expect(await messageLog.get("conv-1")).toEqual([]);
  });
});

describe("sending", () => {
  it("spends a prekey opening a conversation and none keeping it going", async () => {
    // Claiming deletes a single-use key from the recipient's pool. Doing it per
    // message drains the pool of a busy conversation for nothing: the session
    // it opened is still there.
    await sendText("conv-1", 7, "first");
    await sendText("conv-1", 7, "second");
    // A message somebody typed is news, and says so.
    expect(api.sendMessages.mock.calls[0][1].silent).toBe(false);

    expect(api.claimSessionKeys).toHaveBeenCalledTimes(1);
    expect(api.sendMessages).toHaveBeenCalledTimes(2);
  });

  it("addresses this account's other devices as well as theirs", async () => {
    await sendText("conv-1", 7, "hello");

    const [, body] = api.sendMessages.mock.calls[0];
    expect(
      body.messages.map((message: { recipient_device_id: string }) => message.recipient_device_id)
    ).toEqual([THEIRS.device_id, OUR_PHONE.id]);
  });

  it("advances the session once per message when two are sent at once", async () => {
    // Two tabs on the same conversation. A ratchet step read and written
    // without care loses one of them, and the message that claimed the same
    // place in the conversation is one the far end cannot open.
    await sendText("conv-1", 7, "opens the session");

    await Promise.all([sendText("conv-1", 7, "two"), sendText("conv-1", 7, "three")]);

    expect(await sessionPickle.get(`session:${THEIRS.identity_key}`)).toBe("session:theirs!!!");
  });

  it("refuses when none of their devices can be opened either", async () => {
    // A device that published nothing claimable is one this message cannot
    // reach, and if that is all of them the message reaches nobody at all.
    api.claimSessionKeys.mockResolvedValue({
      user_id: 7,
      devices: [{ ...THEIRS, one_time_key: null }],
    });

    await expect(sendText("conv-1", 7, "hello")).rejects.toBeInstanceOf(RecipientHasNoDeviceError);
    expect(api.sendMessages).not.toHaveBeenCalled();
    expect(await messageLog.get("conv-1")).toEqual([]);
  });

  it("refuses to write a message into a thread nobody can receive", async () => {
    api.readDirectory.mockResolvedValue({ user_id: 7, devices: [] });

    await expect(sendText("conv-1", 7, "hello")).rejects.toBeInstanceOf(RecipientHasNoDeviceError);
    expect(api.sendMessages).not.toHaveBeenCalled();
    expect(await messageLog.get("conv-1")).toEqual([]);
  });
});

describe("registering", () => {
  it("withdraws a device it registered after its turn was taken over", async () => {
    // A registration slower than the window the next tab waits out. Both are
    // registered, but only one set of private keys survives — so the device
    // whose keys were dropped is taken back off the server rather than left
    // collecting messages nothing can open.
    await forgetDevice();
    api.registerDevice.mockImplementation(async () => {
      // What the tab that took over did while this registration was in flight.
      const base = Date.now();
      const clock = vi.spyOn(Date, "now").mockReturnValue(base + 31_000);
      const turn = await deviceClaim.take();
      clock.mockRestore();
      await deviceClaim.settle(turn as string, "device-quick", "pickle-quick");
      return { devices: [ownDevice({ id: "device-slow", identity_key: "slow" })] };
    });
    api.removeDevice.mockResolvedValue(undefined);

    await expect(ensureDevice()).resolves.toBe("device-quick");
    expect(api.removeDevice).toHaveBeenCalledWith("device-slow");
    expect(await accountPickle.get()).toBe("pickle-quick");
  });
});

describe("signing out", () => {
  it("takes the device off the server and the messages off this browser", async () => {
    api.removeDevice.mockResolvedValue(undefined);
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from("theirs", "read on this device") })],
    });
    await collect();
    expect(await messageLog.get("conv-1")).toHaveLength(1);

    await forgetMessagesOnThisDevice();

    expect(api.removeDevice).toHaveBeenCalledWith(OURS.id);
    expect(await messageLog.get("conv-1")).toEqual([]);
    expect(await deviceId.get()).toBeUndefined();
    expect(await accountPickle.get()).toBeUndefined();
  });
});

describe("the prekey pool", () => {
  it("is topped back up when it runs low", async () => {
    // Nothing else refills it: the server has never held a private half.
    api.listDevices.mockResolvedValue({ devices: [ownDevice(OURS, 3)] });

    await collect();

    expect(api.topUpKeys).toHaveBeenCalledWith(
      expect.objectContaining({ device_id: OURS.id, one_time_keys: expect.any(Array) })
    );
    expect(api.topUpKeys.mock.calls[0][0].one_time_keys).toHaveLength(47);
  });

  it("is left alone while it is still deep", async () => {
    await collect();

    expect(api.topUpKeys).not.toHaveBeenCalled();
  });

  it("publishes nothing it did not keep the private half of", async () => {
    // The account is written first and the keys published second. A failed
    // write must not leave a key on the server that this device cannot answer.
    await accountPickle.set("account");
    api.listDevices.mockResolvedValue({ devices: [ownDevice(OURS, 0)] });
    api.topUpKeys.mockRejectedValue(new Error("network"));

    await collect();

    expect(await accountPickle.get()).toBe("account+50");
  });
});

/**
 * What counts as unread, on a device that keeps the only copy of the thread.
 *
 * The two sides stamp their messages from two clocks — theirs by the server,
 * mine by this browser — so the marker has to be taken from one of them or the
 * count is a guess about which clock is right.
 */
describe("unread", () => {
  const CONVERSATION = "conv-1";

  it("counts what arrived after the thread was last looked at", async () => {
    await messageLog.append(CONVERSATION, {
      id: "m1",
      body: "first",
      at: "2026-09-01T10:00:00Z",
      mine: false,
    });
    await markRead(CONVERSATION);
    await messageLog.append(CONVERSATION, {
      id: "m2",
      body: "second",
      at: "2026-09-01T11:00:00Z",
      mine: false,
    });

    expect(await unreadIn(CONVERSATION)).toBe(1);
  });

  it("does not count your own", async () => {
    await messageLog.append(CONVERSATION, {
      id: "m1",
      body: "mine",
      at: "2026-09-01T10:00:00Z",
      mine: true,
    });

    expect(await unreadIn(CONVERSATION)).toBe(0);
  });

  it("counts two that landed in the same millisecond", async () => {
    // A burst arrives with one timestamp on all of it. Counted by time, the
    // second one would already be behind the marker the first one set.
    await messageLog.append(CONVERSATION, {
      id: "m1",
      body: "first",
      at: "2026-09-01T10:00:00Z",
      mine: false,
    });
    await markRead(CONVERSATION);
    await messageLog.append(CONVERSATION, {
      id: "m2",
      body: "second, same instant",
      at: "2026-09-01T10:00:00Z",
      mine: false,
    });

    expect(await unreadIn(CONVERSATION)).toBe(1);
  });

  it("survives a browser clock running ahead of the server", async () => {
    // The message this device wrote is stamped from a clock hours ahead. A
    // marker taken from it would swallow everything that arrives next.
    await messageLog.append(CONVERSATION, {
      id: "m1",
      body: "sent from a fast clock",
      at: "2099-01-01T00:00:00Z",
      mine: true,
    });
    await markRead(CONVERSATION);
    await messageLog.append(CONVERSATION, {
      id: "m2",
      body: "their reply, stamped by the server",
      at: "2026-09-01T11:00:00Z",
      mine: false,
    });

    expect(await unreadIn(CONVERSATION)).toBe(1);
  });
});
