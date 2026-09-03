/**
 * The two properties of the local store that keep messages.
 *
 * Both have been lost to a rebase more than once, and neither is visible to the
 * type checker or the linter: an append that clobbers another append still
 * compiles, and a session list that overwrites still compiles. So they are
 * asserted here.
 */

import "fake-indexeddb/auto";

import { beforeEach, describe, expect, it } from "vitest";

import { forgetDevice, messageLog, sessionsInConversation } from "./store";

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

  it("keeps every message when many arrive at once", async () => {
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
