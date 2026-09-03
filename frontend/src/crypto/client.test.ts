/**
 * The client's one rule: everything goes through the worker.
 *
 * There used to be a fallback that called the engine directly where `Worker`
 * was undefined, which put the pickle key in the main thread's realm — the one
 * place the worker exists to keep it out of. This asserts the fallback is gone,
 * because a removed code path is easy to reintroduce by accident.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { ratchet, ratchetSupported } from "./client";

const engine = vi.hoisted(() => ({ createAccount: vi.fn() }));
vi.mock("./engine", () => engine);

const original = globalThis.Worker;

afterEach(() => {
  if (original === undefined) {
    Reflect.deleteProperty(globalThis, "Worker");
  } else {
    globalThis.Worker = original;
  }
  vi.clearAllMocks();
});

describe("the ratchet client", () => {
  it("refuses rather than falling back when there is no worker", async () => {
    Reflect.deleteProperty(globalThis, "Worker");

    await expect(ratchet.createAccount()).rejects.toThrow(/web workers/i);
    // The point of the assertion: it did not quietly run on this thread.
    expect(engine.createAccount).not.toHaveBeenCalled();
  });

  it("says up front whether this runtime can hold a ratchet", () => {
    Reflect.deleteProperty(globalThis, "Worker");
    expect(ratchetSupported()).toBe(false);

    globalThis.Worker = class {} as unknown as typeof Worker;
    expect(ratchetSupported()).toBe(true);
  });
});
