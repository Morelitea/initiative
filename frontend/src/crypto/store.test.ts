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

import { beforeEach, describe, expect, it } from "vitest";

import { deviceClaim, forgetDevice, messageLog, sessionsInConversation } from "./store";

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

describe("the device-registration claim", () => {
  it("is taken by exactly one caller", async () => {
    // Two tabs opening Messages for the first time. Registering twice would
    // leave the server with two devices and this browser with one set of
    // private keys.
    const results = await Promise.all([deviceClaim.take(), deviceClaim.take(), deviceClaim.take()]);

    expect(results.filter(Boolean)).toHaveLength(1);
  });

  it("is not taken again once somebody has registered", async () => {
    await deviceClaim.take();
    await deviceClaim.settle("device-1");

    expect(await deviceClaim.take()).toBe(false);
    expect(await deviceClaim.read()).toEqual({ status: "ready", deviceId: "device-1" });
  });

  it("can be taken again by the next caller when one is handed back", async () => {
    // A tab that failed mid-registration must not hold the claim until it goes
    // stale, or the next attempt waits for nothing.
    expect(await deviceClaim.take()).toBe(true);
    await deviceClaim.release();

    expect(await deviceClaim.take()).toBe(true);
  });

  it("can be forced open when the recorded device is gone", async () => {
    await deviceClaim.take();
    await deviceClaim.settle("device-1");
    await deviceClaim.invalidate();

    expect(await deviceClaim.take()).toBe(true);
  });
});
