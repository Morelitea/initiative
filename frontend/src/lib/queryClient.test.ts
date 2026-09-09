/**
 * The client-wide fetch policy, which is the difference between two people
 * seeing the same board and one of them pressing reload.
 *
 * The two defaults only work as a pair — the flag is what makes a returning
 * tab ask at all, and the window is what stops it asking for everything every
 * time somebody alt-tabs — so they are asserted through behaviour rather than
 * by reading the options back.
 */
import { focusManager, QueryObserver } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryClient } from "./queryClient";

/** Leave and return, which is what the focus manager calls a focus. */
const refocus = () => {
  focusManager.setFocused(false);
  focusManager.setFocused(true);
};

/**
 * A subscribed query, settled. Nothing may be asserted about a second fetch
 * until the first has landed: while one is in flight the client dedupes
 * against it, and its result would overwrite any backdating done meanwhile.
 */
const observeSettled = async (queryKey: readonly unknown[], queryFn: () => Promise<unknown>) => {
  const observer = new QueryObserver(queryClient, { queryKey, queryFn });
  const unsubscribe = observer.subscribe(() => {});
  await vi.waitFor(() => expect(observer.getCurrentResult().isSuccess).toBe(true));
  return unsubscribe;
};

/** Backdate a cached answer so it reads as older than the stale window. */
const age = (queryKey: readonly unknown[], value: unknown, msAgo: number) => {
  queryClient.setQueryData(queryKey, value, { updatedAt: Date.now() - msAgo });
};

// The provider is what wires the client to the focus manager in the app, and
// there is no provider here — without this the client hears no focus at all.
beforeEach(() => {
  queryClient.mount();
});

afterEach(() => {
  queryClient.unmount();
  // Hand the focus state back to the document; the client is a module
  // singleton shared with whatever runs next in this process.
  focusManager.setFocused(undefined);
  queryClient.clear();
});

describe("queryClient defaults", () => {
  it("refetches on focus once the answer has aged past the window", async () => {
    const queryFn = vi.fn().mockResolvedValue("fresh");
    const unsubscribe = await observeSettled(["focus", "stale"], queryFn);

    age(["focus", "stale"], "old", 60_000);
    refocus();

    await vi.waitFor(() => expect(queryFn).toHaveBeenCalledTimes(2));
    unsubscribe();
  });

  it("asks for nothing on focus while the answer is still fresh", async () => {
    const queryFn = vi.fn().mockResolvedValue("fresh");
    const unsubscribe = await observeSettled(["focus", "fresh"], queryFn);

    refocus();
    await Promise.resolve();

    expect(queryFn).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("still refetches an invalidated query, however fresh it looks", async () => {
    const queryFn = vi.fn().mockResolvedValue("fresh");
    const unsubscribe = await observeSettled(["focus", "invalidated"], queryFn);

    // What the realtime bus does when somebody else writes. The stale window
    // governs the fetches nothing asked for, never this one.
    await queryClient.invalidateQueries({ queryKey: ["focus", "invalidated"] });

    expect(queryFn).toHaveBeenCalledTimes(2);
    unsubscribe();
  });
});
