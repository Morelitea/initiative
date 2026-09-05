/**
 * The two properties of the local store that keep messages.
 *
 * Both have been lost to a rebase more than once, and neither is visible to the
 * type checker or the linter: an append that clobbers another append still
 * compiles, and a session list that overwrites still compiles. So they are
 * asserted here.
 *
 * Each call opens its own connection to the database, which is what a second
 * tab is — so these races are the cross-tab ones, not merely two promises in
 * one module. That is why the atomicity has to live in an IndexedDB
 * transaction: a JavaScript lock would pass these tests and still lose a
 * message between two windows.
 */

import "fake-indexeddb/auto";

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  accountPickle,
  deviceClaim,
  deviceId,
  forgetDevice,
  messageLog,
  sessionOrigin,
  sessionsInConversation,
} from "./store";

beforeEach(async () => {
  await forgetDevice();
});

describe("the message log", () => {
  it("keeps both of two appends that race", async () => {
    // Sending and collecting are independently reachable and both append. A
    // plain read-modify-write loses whichever finishes first.
    await Promise.all([
      messageLog.append("conv", { id: "a", body: "first", at: "", mine: true }),
      messageLog.append("conv", { id: "b", body: "second", at: "", mine: false }),
    ]);

    const stored = await messageLog.get("conv");
    expect(stored.map((entry) => entry.id).sort()).toEqual(["a", "b"]);
  });

  it("keeps every message when many arrive at once, across connections", async () => {
    const messages = Array.from({ length: 12 }, (_, index) => ({
      id: String(index),
      body: `m${index}`,
      at: "",
      mine: false,
    }));

    await Promise.all(messages.map((message) => messageLog.append("conv", message)));

    expect(await messageLog.get("conv")).toHaveLength(12);
  });

  it("ignores a message it already holds", async () => {
    const message = { id: "a", body: "once", at: "", mine: true };
    await messageLog.append("conv", message);
    await messageLog.append("conv", message);

    expect(await messageLog.get("conv")).toHaveLength(1);
  });

  it("keeps conversations apart", async () => {
    await messageLog.append("one", { id: "a", body: "x", at: "", mine: true });
    await messageLog.append("two", { id: "b", body: "y", at: "", mine: true });

    expect(await messageLog.get("one")).toHaveLength(1);
    expect(await messageLog.get("two")).toHaveLength(1);
  });
});

describe("acting on a message already said", () => {
  const mine = { id: "m", body: "mine", at: "2026-01-01T00:00:00Z", mine: true };
  const theirs = { id: "t", body: "theirs", at: "2026-01-01T00:00:00Z", mine: false };

  beforeEach(async () => {
    await messageLog.append("conv", mine);
    await messageLog.append("conv", theirs);
  });

  it("counts both sides behind one emoji, and drops it when neither is", async () => {
    await messageLog.applyReaction("conv", "t", "🎲", true, "mine");
    await messageLog.applyReaction("conv", "t", "🎲", true, "theirs");

    let stored = await messageLog.get("conv");
    expect(stored.find((entry) => entry.id === "t")?.reactions).toEqual({
      "🎲": { mine: true, theirs: true },
    });

    await messageLog.applyReaction("conv", "t", "🎲", false, "mine");
    await messageLog.applyReaction("conv", "t", "🎲", false, "theirs");

    stored = await messageLog.get("conv");
    // Not an emoji with nobody behind it: it stops being a reaction.
    expect(stored.find((entry) => entry.id === "t")?.reactions).toEqual({});
  });

  it("takes the same reaction twice as one", async () => {
    expect(await messageLog.applyReaction("conv", "t", "👍", true, "theirs")).toBe(true);
    // Both a tab that sent it and a tab that collected it can present it.
    expect(await messageLog.applyReaction("conv", "t", "👍", true, "theirs")).toBe(false);
  });

  it("lets each side rewrite only what it said", async () => {
    expect(
      await messageLog.applyEdit("conv", "m", "changed", "2026-01-02T00:00:00Z", "mine", 1)
    ).toBe(true);
    // Their envelope naming your message changes nothing, whatever it claims.
    expect(
      await messageLog.applyEdit("conv", "m", "hijacked", "2026-01-03T00:00:00Z", "theirs", 2)
    ).toBe(false);

    const stored = await messageLog.get("conv");
    expect(stored.find((entry) => entry.id === "m")?.body).toBe("changed");
  });

  it("keeps the newest edit whichever order two arrive in", async () => {
    await messageLog.applyEdit("conv", "m", "second", "2026-01-03T00:00:00Z", "mine", 2);
    await messageLog.applyEdit("conv", "m", "first", "2026-01-02T00:00:00Z", "mine", 1);

    const stored = await messageLog.get("conv");
    expect(stored.find((entry) => entry.id === "m")?.body).toBe("second");
  });

  it("orders edits by revision rather than by the device's clock", async () => {
    // Two devices of one account, clocks set independently: the correction
    // made second carries the earlier time, and losing to the one it was meant
    // to replace would leave the two of them holding different words forever.
    await messageLog.applyEdit("conv", "m", "typo", "2026-01-05T00:00:00Z", "mine", 1);
    await messageLog.applyEdit("conv", "m", "fixed", "2026-01-02T00:00:00Z", "mine", 2);

    const stored = await messageLog.get("conv");
    expect(stored.find((entry) => entry.id === "m")?.body).toBe("fixed");
  });

  it("settles two edits that reached the same revision the same way everywhere", async () => {
    // Arbitrary, but the same arbitrary answer on every device that sees both:
    // one that agrees beats a sensible one that does not.
    const order = async (first: string, second: string) => {
      await forgetDevice();
      await messageLog.append("conv", mine);
      await messageLog.applyEdit("conv", "m", first, "2026-01-02T00:00:00Z", "mine", 1);
      await messageLog.applyEdit("conv", "m", second, "2026-01-03T00:00:00Z", "mine", 1);
      return (await messageLog.get("conv")).find((entry) => entry.id === "m")?.body;
    };

    expect(await order("apple", "banana")).toBe(await order("banana", "apple"));
  });

  it("lets each side take back only what it said", async () => {
    expect(await messageLog.applyRemove("conv", "t", "mine", "2026-01-02T00:00:00Z")).toBe(false);
    expect(await messageLog.applyRemove("conv", "t", "theirs", "2026-01-02T00:00:00Z")).toBe(true);

    // The entry stays, so a thread does not close over the gap.
    const stored = await messageLog.get("conv");
    expect(stored.map((entry) => entry.id)).toEqual(["m", "t"]);
    expect(stored[1]).toEqual({
      id: "t",
      at: "2026-01-01T00:00:00Z",
      mine: false,
      replyTo: undefined,
      body: "",
      removedAt: "2026-01-02T00:00:00Z",
    });
  });

  it("takes the reactions and the receipt with it", async () => {
    await messageLog.applyReaction("conv", "t", "👍", true, "mine");
    await messageLog.applyRemove("conv", "t", "theirs", "2026-01-02T00:00:00Z");

    const stored = await messageLog.get("conv");
    expect(stored[1].reactions).toBeUndefined();
  });

  it("leaves nothing to land on a message already taken back", async () => {
    await messageLog.applyRemove("conv", "t", "theirs", "2026-01-02T00:00:00Z");

    expect(await messageLog.applyReaction("conv", "t", "👍", true, "mine")).toBe(false);
    expect(
      await messageLog.applyEdit("conv", "t", "back again", "2026-01-03T00:00:00Z", "theirs", 1)
    ).toBe(false);
  });
});

describe("the sessions a conversation holds", () => {
  it("accumulates one per device rather than replacing", async () => {
    // The other party may have several devices, and each is its own ratchet.
    // Keeping one id per conversation makes the second device's messages
    // undecryptable.
    await sessionsInConversation.add("conv", "session-laptop");
    await sessionsInConversation.add("conv", "session-phone");

    expect(await sessionsInConversation.get("conv")).toEqual(["session-phone", "session-laptop"]);
  });

  it("does not list the same session twice", async () => {
    await sessionsInConversation.add("conv", "session-a");
    await sessionsInConversation.add("conv", "session-a");

    expect(await sessionsInConversation.get("conv")).toEqual(["session-a"]);
  });
});

describe("the account", () => {
  it("is replaced only by a writer that read what is stored", async () => {
    // The account holds the private half of every published prekey. Two tabs
    // advancing it from the same starting point — one collecting, one topping
    // up — would otherwise leave published keys with no private half.
    await accountPickle.set("first");

    expect(await accountPickle.swap("first", "second")).toBe(true);
    expect(await accountPickle.swap("first", "third")).toBe(false);
    expect(await accountPickle.get()).toBe("second");
  });

  it("admits exactly one of two writers that raced", async () => {
    await accountPickle.set("first");

    const results = await Promise.all([
      accountPickle.swap("first", "collected"),
      accountPickle.swap("first", "topped-up"),
    ]);

    expect(results.filter(Boolean)).toHaveLength(1);
  });
});

describe("which side a session belongs to", () => {
  it("is remembered per session", async () => {
    await sessionOrigin.set("session-theirs", "other");
    await sessionOrigin.set("session-my-phone", "self");

    expect(await sessionOrigin.get("session-theirs")).toBe("other");
    expect(await sessionOrigin.get("session-my-phone")).toBe("self");
    expect(await sessionOrigin.get("session-unknown")).toBeUndefined();
  });
});

describe("the device-registration claim", () => {
  /** Past the window after which an abandoned claim may be taken over. */
  const STALE = 31_000;

  it("is taken by exactly one caller", async () => {
    // Two tabs opening Messages for the first time. Registering twice would
    // leave the server with two devices and this browser with one set of
    // private keys.
    const results = await Promise.all([deviceClaim.take(), deviceClaim.take(), deviceClaim.take()]);

    expect(results.filter(Boolean)).toHaveLength(1);
  });

  it("writes the keys, the id and the claim together", async () => {
    // One transaction: a tab that sees the claim settled must find everything
    // the device id refers to already there.
    const turn = await take();

    expect(await deviceClaim.settle(turn, "device-1", "pickle-1")).toBe(true);
    expect(await accountPickle.get()).toBe("pickle-1");
    expect(await deviceId.get()).toBe("device-1");
  });

  it("is not taken again once somebody has registered", async () => {
    const turn = await take();
    await deviceClaim.settle(turn, "device-1", "pickle-1");

    expect(await deviceClaim.take()).toBeNull();
    expect(await deviceClaim.read()).toEqual({ status: "ready", deviceId: "device-1" });
  });

  it("can be taken again by the next caller when one is handed back", async () => {
    // A tab that failed mid-registration must not hold the claim until it goes
    // stale, or the next attempt waits for nothing.
    const turn = await take();
    await deviceClaim.release(turn);

    expect(await deviceClaim.take()).not.toBeNull();
  });

  it("can be forced open when the recorded device is gone", async () => {
    const turn = await take();
    await deviceClaim.settle(turn, "device-1", "pickle-1");
    await deviceClaim.invalidate("device-1");

    expect(await deviceClaim.take()).not.toBeNull();
  });

  it("leaves a claim somebody is already registering under alone", async () => {
    // One tab noticed the revocation first and is mid-registration. A second
    // tab reaching the same conclusion must wait for it, not reopen the claim
    // and register a competing device.
    const turn = await take();
    await deviceClaim.settle(turn, "device-1", "pickle-1");
    await deviceClaim.invalidate("device-1");
    expect(await deviceClaim.take()).not.toBeNull();

    await deviceClaim.invalidate("device-1");

    expect(await deviceClaim.take()).toBeNull();
  });

  it("is not reopened by a device other than the recorded one", async () => {
    const turn = await take();
    await deviceClaim.settle(turn, "device-2", "pickle-2");

    await deviceClaim.invalidate("device-1");

    expect(await deviceClaim.take()).toBeNull();
    expect(await deviceClaim.read()).toEqual({ status: "ready", deviceId: "device-2" });
  });

  it("cannot be settled by a caller whose turn was taken over", async () => {
    // A registration slower than the window the next tab waits out. Both
    // registered a device; only one set of private keys can be kept, and it has
    // to be the one belonging to the device the claim now names.
    const slow = await take();
    const quick = await afterStale(() => take());
    await deviceClaim.settle(quick, "device-quick", "pickle-quick");

    expect(await deviceClaim.settle(slow, "device-slow", "pickle-slow")).toBe(false);
    expect(await accountPickle.get()).toBe("pickle-quick");
    expect(await deviceId.get()).toBe("device-quick");
  });

  it("is not handed back by a caller whose turn was taken over", async () => {
    const slow = await take();
    const quick = await afterStale(() => take());

    await deviceClaim.release(slow);

    expect(await deviceClaim.take()).toBeNull();
    expect(await deviceClaim.read()).toMatchObject({ status: "claiming", token: quick });
  });

  /** Take the claim, failing the test rather than the assertion if it is held. */
  async function take(): Promise<string> {
    const turn = await deviceClaim.take();
    expect(turn).not.toBeNull();
    return turn as string;
  }

  /** Run something as though the stale window had passed. */
  async function afterStale<T>(work: () => Promise<T>): Promise<T> {
    const base = Date.now();
    const clock = vi.spyOn(Date, "now").mockReturnValue(base + STALE);
    try {
      return await work();
    } finally {
      clock.mockRestore();
    }
  }
});
