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
      return {
        account_pickle: `${pickle}-spent`,
        session_pickle: `session:${identity}`,
        session_id: `session:${identity}`,
        plaintext: message.body,
      };
    },
    encrypt: async (sessionPickle: string, plaintext: string) => ({
      session_pickle: sessionPickle,
      message_type: 1,
      ciphertext: JSON.stringify({ from: "mine", body: plaintext }),
    }),
    decrypt: async (sessionPickle: string, _type: number, ciphertext: string) => {
      const message = JSON.parse(ciphertext);
      if (sessionPickle !== `session:${message.from}`) throw new Error("not this session");
      return { session_pickle: sessionPickle, plaintext: message.body };
    },
  },
}));

import { collect, RecipientHasNoDeviceError, sendText } from "./messaging";
import { accountPickle, deviceId, forgetDevice, messageLog } from "./store";

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

const from = (identity: string, body: string) => JSON.stringify({ from: identity, body });

beforeEach(async () => {
  await forgetDevice();
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
